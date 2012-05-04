#!/usr/bin/env python

import fileinput
import json
import optparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings

class GMakeCommand(object):
  """Parse a GNU make command line to see which args affect build output.

  Some flags (e.g. -w) have no semantic content. Others (targets in
  particular) always do. Variable assignments may or may not but must
  be assumed to change semantics. Last, there's the category of flags
  (-n, -d) which indicate that this is some kind of test and not a
  production build. This class attempts to categorize the command line
  in these ways and produce a unique key composed from the targets and
  variable assignments.

  """
  class PassThroughOptionParser(optparse.OptionParser):
    """Subclass of OptionParser which passes unrecognized flags through."""
    def _process_args(self, largs, rargs, values):
      while rargs:
        try:
          optparse.OptionParser._process_args(self,largs,rargs,values)
        except (optparse.BadOptionError,optparse.AmbiguousOptionError), e:
          largs.append(e.opt_str)

  def __init__(self, argv):
    self.argv = argv

    # Strip out the flags which don't change build artifacts.
    parse_ignored = GMakeCommand.PassThroughOptionParser()
    parse_ignored.add_option('-f', '--file', type='string')
    parse_ignored.add_option('-j', '--jobs', type='string')
    parse_ignored.add_option('-l', '--load-average', type='string')
    parse_ignored.add_option('-s', '--silent', action='store_true')
    parse_ignored.add_option('-w', '--print-directory', action='store_true')
    parse_ignored.add_option(      '--no-print-directory', action='store_true')
    parse_ignored.add_option(      '--warn-undefined-variables', action='store_true')
    ignored_opts, survivors = parse_ignored.parse_args(argv[1:])

    # Grab the flag that changes the actual build dir if present;
    # we'll need it.
    parse_dir = GMakeCommand.PassThroughOptionParser()
    parse_dir.add_option('-C', '--directory', type='string')
    dir_opts, leftovers = parse_dir.parse_args(survivors)
    self.subdir = dir_opts.directory if dir_opts.directory else '.'

    # Look for the flags that mark this as a special case build,
    # one which is not worth auditing.
    parse_spec = GMakeCommand.PassThroughOptionParser()
    parse_spec.add_option('-B', '--always-make', action='store_true', dest="set")
    parse_spec.add_option('-e', '--environment-overrides', action='store_true', dest="set")
    parse_spec.add_option('-I', '--include-dir', type='string', dest="set")
    parse_spec.add_option('-i', '--ignore-errors', action='store_true', dest="set")
    parse_spec.add_option('-k', '--keep-going', action='store_true', dest="set")
    parse_spec.add_option('-L', '--check-symlink-times', action='store_true', dest="set")
    parse_spec.add_option('-n', '--dry-run', action='store_true', dest="set")
    parse_spec.add_option('-o', '--old-file', type='string', dest="set")
    parse_spec.add_option('-p', '--print-data-base', action='store_true', dest="set")
    parse_spec.add_option('-q', '--question', action='store_true', dest="set")
    parse_spec.add_option('-R', '--no-builtin-variables', action='store_true', dest="set")
    parse_spec.add_option('-r', '--no-builtin-rules', action='store_true', dest="set")
    parse_spec.add_option('-S', '--no-keep-going', action='store_true', dest="set")
    parse_spec.add_option('-t', '--touch', action='store_true', dest="set")
    parse_spec.add_option('-v', '--version', action='store_true', dest="set")
    parse_spec.add_option('-W', '--what-if', action='store_true', dest="set")
    special_opts, remains = parse_spec.parse_args(leftovers)
    self.special_case = True if special_opts.set is not None else False

    makeflags = os.getenv('MAKEFLAGS', '')
    makeflags = re.sub(r'\s+--\s+.*', '', makeflags)
    makeflags = re.sub(r'\s*--\S+', '', makeflags)
    makeflags = re.sub(r'\S+=\S+', '', makeflags)
    if re.search(r'[BeIikLnopqRrStvW]', makeflags):
      self.special_case = True
    self.dry_run = 'n' in makeflags

    keys = []
    for word in remains:
      if not re.match(r'(JOBS|PAR|V|VERBOSE|AM_DIR|AM_FLAGS)=', word):
        keys.append(word)

    if keys:
      k = '_'.join(sorted(keys))
      self.tgtkey = k.replace(os.sep, '@')
    else:
      self.tgtkey = 'DEFAULT'

  def execute_in(self, dir):
    verbose(self.argv)
    return subprocess.call(self.argv, cwd=dir)

  def clean_in(self, dir):
    cleancmd = [self.argv[0], 'clean']
    verbose(cleancmd)
    return subprocess.call(cleancmd, cwd=dir)

class BuildAudit:
  """Class to manage and persist the audit of a build into prereqs and targets.

  The files used during a build can be categorized as prerequisites (read from)
  and targets (written to). Some are both, but a write beats a read so we treat
  any file modified as a target. This class manages a data structure
  categorizing the two sets. It also records the time delta for each file from
  start of build until last use.

  """
  def __init__(self, dbdir):
    self.dbfile = os.path.join(dbdir, 'BuildAudit.json')
    try:
      self.db = json.load(open(self.dbfile))
    except IOError:
      self.db = {}
    self.audit = {'PREREQS':{}, 'TARGETS':{}, 'CMDLINE':sys.argv}
    self.new_prereqs = self.audit['PREREQS']
    self.new_targets = self.audit['TARGETS']

  def old_prereqs(self, key):
    return self.db[key]['PREREQS'] if key in self.db else {}

  def old_targets(self, key):
    return self.db[key]['TARGETS'] if key in self.db else {}

  def add_prereq(self, path, delta):
    self.new_prereqs[path] = delta

  def add_target(self, path, delta):
    self.new_targets[path] = delta

  def print_prereqs(self, key):
    for p in sorted(self.old_prereqs(key)):
      print p

  def print_targets(self, key):
    for p in sorted(self.old_targets(key)):
      print p

  def dump(self, key, replace):
    if not self.new_prereqs:
      warnings.warn("Empty prereq set - check for 'noatime' mount")
    else:
      if replace or key not in self.db:
        self.db[key] = {'PREREQS':{}, 'TARGETS':{}, 'CMDLINE':sys.argv}
      old_prqs = self.old_prereqs(key)
      old_tgts = self.old_targets(key)
      if set(self.new_prereqs) - set(old_prqs) or \
         set(self.new_targets) - set(old_tgts):
        self.new_prereqs.update(old_prqs)
        self.new_targets.update(old_tgts)
        self.db[key] = {'PREREQS':self.new_prereqs, 'TARGETS':self.new_targets, 'CMDLINE':sys.argv}
        print >> sys.stderr, "%s: updating database for '%s'" % (prog, key)
        with open(self.dbfile, "w") as fp:
          json.dump(self.db, fp, indent=2)
          fp.write('\n');  # json does not add trailing newline

def verbose(cmd):
  """Print verbosity for executed subcommands."""
  print >> sys.stderr, '+', ' '.join(cmd)

def get_ref_time(localdir):
  """Return a unique file reference time.

  Different filesystems have different granularity for time stamps.
  For instance, ext3 records only 1-second granularity while ext4 records
  nanoseconds. Regardless of host filesystem, this function guarantees to
  return a timestamp value older than any file subsequently accessed in
  the same filesystem and same thread, and newer than any file previously
  touched.

  """
  def get_time_past(previous):
    this_time = 0
    while True:
      with tempfile.TemporaryFile(dir=localdir) as fp:
        this_time = os.fstat(fp.fileno()).st_mtime
      if this_time > previous:
        break
      time.sleep(0.1)
    return this_time

  old_time = get_time_past(0)
  ref_time = get_time_past(old_time)
  # Don't need to wait the second interval since comparisons are >= 0.
  #new_time = get_time_past(ref_time)
  return ref_time

def run_with_stdin(cmd, input):
  verbose(cmd)
  subproc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
  for line in input:
    print >> subproc.stdin, line
  subproc.stdin.close()
  if subproc.wait():
    sys.exit(2)

def main(argv):
  """Do an audited GNU make build, optionally moved to a local directory.

  The default build auditing mechanism here is the simplest possible:
  The build is started and the starting time noted. When it finishes,
  each file in the build tree is stat-ed. If its modification time
  (mtime) is newer than the starting time it's considered to be
  a build artifact, aka target. If only the access time (atime)
  is newer, it's considered a source file, aka prerequisite. If
  neither, it was unused. Results are kept in a simple dictionary
  structure keyed by build target.

  A mechanism is included for copying required files into a different
  directory tree, building there, and copying the results back.
  The most common use case would be to offload from an NFS-mounted
  area to a local filesystem, for speed reasons, but that is not
  required. The requirement is that the build filesystem must update
  access times, i.e. not be mounted with the "noatime" option. NFS
  mounts often employ "noatime" as an optimization.

  """

  global prog
  prog = os.path.basename(argv[0])

  msg = prog
  msg += ' -b|--base-of-tree <dir>'
  msg += ' -c|--clean'
  msg += ' -e|--edit'
  msg += ' -f|--fresh'
  msg += ' -k|--key'
  msg += ' -l|--local-dir <dir>'
  msg += ' -p|--print-prerequisites'
  msg += ' -r|--retry-fresh'
  msg += ' -t|--print-targets'
  msg += ' -- gmake <gmake-args>...'
  parser = optparse.OptionParser(usage=msg)
  parser.add_option('-b', '--base-of-tree', type='string',
          help='Path to root of source tree')
  parser.add_option('-c', '--clean', action='store_true',
          help='Force a make clean ahead of the build')
  parser.add_option('-e', '--edit', action='store_true',
          help='Fix generated text files to use ${AM_DIR}')
  parser.add_option('-f', '--fresh', action='store_true',
          help='Regenerate data for current build from scratch')
  parser.add_option('-k', '--key', type='string',
          help='Key uniquely describing what was built')
  parser.add_option('-l', '--local-dir', type='string',
          help='Path of local directory')
  parser.add_option('-p', '--print-prereqs', action='store_true',
          help='Print a list of known prerequisites for the given key')
  parser.add_option('-r', '--retry-fresh', action='store_true',
          help='On build failure, try a full fresh rebuild')
  parser.add_option('-t', '--print-targets', action='store_true',
          help='Print a list of known targets for the given key')

  options, left = parser.parse_args(argv[1:])
  if options.fresh and options.retry_fresh:
    parser.error("the --fresh and --retry-fresh options are incompatible")
  if options.edit and not options.local_dir:
    parser.error("the --edit option makes no sense without --local-dir")

  base_dir = os.path.abspath(options.base_of_tree if options.base_of_tree else '.')

  cwd = os.getcwd()

  bldcmd = GMakeCommand(left)

  if options.local_dir and not bldcmd.special_case:
    local_dir = os.path.abspath(options.local_dir)
    build_base = os.path.abspath(local_dir + os.sep + base_dir)
    lwd = os.path.abspath(local_dir + os.sep + cwd)
    if not os.path.exists(lwd):
      options.fresh = True
  else:
    local_dir = None
    build_base = base_dir
    lwd = cwd

  if bldcmd.argv:
    bldcmd.directory = lwd
    audit = BuildAudit(bldcmd.subdir)
  elif options.key:
    audit = BuildAudit('.')
    if not options.print_prereqs and not options.print_targets:
      main([argv[0], "-h"])
    if options.print_prereqs:
      audit.print_prereqs(options.key)
    if options.print_targets:
      audit.print_targets(options.key)
    sys.exit(0)
  else:
    main([argv[0], "-h"])

  if bldcmd.dry_run:
    sys.exit(0)
  elif bldcmd.special_case:
    rc = bldcmd.execute_in(cwd)
    sys.exit(rc)

  # Do an early make clean to get rid of existing artifacts
  if options.fresh or options.clean:
    if bldcmd.clean_in(cwd) != 0:
      sys.exit(2)

  key = options.key if options.key else bldcmd.tgtkey

  if local_dir:
    if options.fresh:
      shutil.rmtree(build_base)
      os.makedirs(lwd)
      stat_cmd = ['svn', 'status', '--no-ignore']
      verbose(stat_cmd)
      svnstat = subprocess.Popen(stat_cmd, stdout=subprocess.PIPE, cwd=base_dir)
      privates = svnstat.communicate()[0]
      if svnstat.returncode != 0:
        sys.exit(2)
      feed_to_rsync = []
      for line in privates.splitlines():
        rpath = re.sub(r'^[I?]\s+', '', line)
        if rpath == line:
          continue
        if re.search(r'vers\w*\.h$', rpath):
          continue
        if os.path.isdir(os.path.join(base_dir, rpath)):
          rpath += os.sep
        feed_to_rsync.append(rpath)
      copy_out_cmd = ['rsync', '-aC', '--exclude-from=-']
    else:
      if options.clean:
        for tgt in audit.old_targets(key):
          try:
            os.remove(os.path.join(build_base, tgt))
          except OSError:
            pass
      feed_to_rsync = audit.old_prereqs(key)
      copy_out_cmd = ['rsync', '-aC', '--files-from=-']

    copy_out_cmd.extend([
        '--delete',
        '--delete-excluded',
        '--exclude=*.swp',
        '--exclude=' + os.path.basename(audit.dbfile),
        base_dir + os.sep,
        build_base])
    run_with_stdin(copy_out_cmd, feed_to_rsync)

    os.putenv('AM_DIR', local_dir)

  reftime = get_ref_time(lwd)

  rc = bldcmd.execute_in(lwd)

  if rc == 0:
    for parent, dir_names, file_names in os.walk(build_base):
      # Assume hidden dirs contain stuff we don't care about
      dir_names[:] = (d for d in dir_names if not d.startswith('.'))

      for file_name in file_names:
        if file_name == os.path.basename(audit.dbfile):
          continue
        path = os.path.join(parent, file_name)
        stats = os.lstat(path)
        adelta = stats.st_atime - reftime
        if adelta < 0:
          continue
        mdelta = stats.st_mtime - reftime
        rpath = os.path.relpath(path, build_base)
        if mdelta >= 0:
          audit.add_target(rpath, mdelta)
        else:
          audit.add_prereq(rpath, adelta)
    audit.dump(key, options.fresh)
  elif options.retry_fresh and local_dir:
    nargv = []
    for arg in argv:
      if not re.match(r'(-r|--retry)', arg):
        nargv.append(arg)
    nargv.insert(1, '--fresh')
    verbose(nargv)
    rc = subprocess.call(nargv)
    sys.exit(rc)

  if local_dir:
    copy_back_cmd = ['rsync', '-a', build_base + os.sep, base_dir, '--files-from=-']
    run_with_stdin(copy_back_cmd, audit.new_targets)
    if options.edit and audit.new_targets:
      # TODO: better to write something like Perl's -T (text) test here
      tgts = [os.path.join(base_dir, t) for t in audit.new_targets if re.search(r'\.(cmd|depend|d|flags)$', t)]
      if tgts:
        mldir = local_dir + os.sep
        for line in fileinput.input(tgts, inplace=True):
          sys.stdout.write(line.replace(mldir, '/'))

  sys.exit(rc)

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
