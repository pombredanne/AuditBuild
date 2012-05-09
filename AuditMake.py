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

    self.assignments = []
    self.targets = []
    for word in remains:
      if '=' in word:
        self.assignments.append(word)
      else:
        self.targets.append(word)

    assigns = []
    for word in self.assignments:
      if not re.match(r'(JOBS|PAR|V|VERBOSE|AM_DIR|AM_FLAGS)=', word):
        assigns.append(word)
    self.tgtkey = '__'.join(sorted(assigns))
    if self.tgtkey:
      self.tgtkey += ';'
    if self.targets:
      self.tgtkey += ':'.join(sorted(self.targets))
    else:
      self.tgtkey += 'all'  #just by convention

  def execute_in(self, dir):
    verbose(self.argv)
    return subprocess.call(self.argv, cwd=dir, stdin=open(os.devnull))

class BuildAudit:
  """Class to manage and persist the audit of a build into prereqs and targets.

  The files used during a build can be categorized as prerequisites (read from)
  and targets (written to). Some are both, but a write beats a read so any
  modified file is treated as a target. This class manages a data structure
  categorizing these file sets. It also records the time delta for each file from
  start of build to last use.

  """
  def __init__(self, dbdir='.', dbname='BuildAudit.json'):
    self.dbfile = os.path.join(dbdir, dbname)
    try:
      self.db = json.load(open(self.dbfile))
    except IOError:
      self.db = {}
    self.audit = {'PREREQS':{}, 'INTERMS':{}, 'TARGETS':{}, 'NOTUSED':{}, 'CMDLINE':sys.argv}
    self.new_prereqs = self.audit['PREREQS']
    self.new_interms = self.audit['INTERMS']
    self.new_targets = self.audit['TARGETS']
    self.new_notused = self.audit['NOTUSED']

  def has(self, key):
    return key in self.db

  def all_keys(self):
    return sorted(self.db.keys())

  def old_prereqs(self, key):
    return self.db[key]['PREREQS'] if key in self.db else {}

  def old_interms(self, key):
    return self.db[key]['INTERMS'] if key in self.db else {}

  def old_targets(self, key):
    return self.db[key]['TARGETS'] if key in self.db else {}

  def old_notused(self, key):
    return self.db[key]['NOTUSED'] if key in self.db else {}

  def get_reftime(self, indir):
    """Return a unique file reference time.

    Different filesystems have different granularities for time
    stamps. For instance, ext3 records one-second granularity while
    ext4 records nanoseconds. Regardless of host filesystem, this
    method guarantees to return a timestamp value newer than any
    file previously accessed within the same filesystem and same
    thread, and no newer than any timestamp created subsequently.

    """
    def get_time_past(previous):
      this_time = 0
      while True:
        with tempfile.TemporaryFile(dir=indir) as fp:
          this_time = os.fstat(fp.fileno()).st_mtime
        if this_time > previous:
          break
        time.sleep(0.1)
      return this_time

    old_time = get_time_past(0)
    self.reftime = get_time_past(old_time)

  def update(self, key, basedir, replace):
    # Note: do NOT use os.walk to traverse the tree.
    # It has a way of updating symlink atimes.
    def visit(data, parent, files):
      # Assume hidden dirs contain stuff we don't care about
      if not parent.startswith('.'):
        for f in files:
          path = os.path.join(parent, f)
          if not os.path.isdir(path):
            rpath = os.path.relpath(path, basedir)
            stats = os.lstat(path)
            adelta = stats.st_atime - self.reftime
            mdelta = stats.st_mtime - self.reftime
            value = str(adelta) + ' ' + str(mdelta)
            if mdelta >= 0:
              if adelta > mdelta:
                self.new_interms[rpath] = 'I ' + value
              else:
                self.new_targets[rpath] = 'T ' + value
            elif adelta >= 0:
              self.new_prereqs[rpath] = 'P ' + value
            else:
              self.new_notused[rpath] = 'N ' + value
    os.path.walk(basedir, visit, None)

    if not self.new_prereqs:
      warnings.warn("Empty prereq set - check for 'noatime' mount")
    else:
      if replace or not self.has(key):
        self.db[key] = {'PREREQS':{}, 'INTERMS':{}, 'TARGETS':{}, 'NOTUSED':{}, 'CMDLINE':sys.argv}
      old_prqs = self.old_prereqs(key)
      old_ints = self.old_interms(key)
      old_tgts = self.old_targets(key)
      if set(self.new_prereqs) - set(old_prqs) or \
         set(self.new_interms) - set(old_ints) or \
         set(self.new_targets) - set(old_tgts):
        self.new_prereqs.update(old_prqs)
        self.new_interms.update(old_ints)
        self.new_targets.update(old_tgts)
        timestr = "%s (%s)" % (str(self.reftime), time.ctime(self.reftime))
        self.db[key] = {'PREREQS':self.new_prereqs, 'INTERMS':self.new_interms, 'TARGETS':self.new_targets,
            'NOTUSED':self.new_notused, 'CMDLINE':sys.argv, 'REFTIME':timestr}
        print >> sys.stderr, "%s: updating database for '%s'" % (prog, key)
        with open(self.dbfile, "w") as fp:
          json.dump(self.db, fp, indent=2)
          fp.write('\n');  # json does not add trailing newline

def verbose(cmd):
  """Print verbosity for executed subcommands."""
  print >> sys.stderr, '+', ' '.join(cmd)

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

  msg = '%prog'
  msg += ' -b|--base-of-tree <dir>'
  msg += ' -c|--clean'
  msg += ' -e|--edit'
  msg += ' -f|--fresh'
  msg += ' -k|--key'
  msg += ' -l|--local-dir <dir>'
  msg += ' -r|--retry-fresh'
  msg += ' -- gmake <gmake-args>...'
  parser = optparse.OptionParser(usage=msg)
  parser.add_option('-b', '--base-of-tree', type='string',
          help='Path to root of source tree')
  parser.add_option('-c', '--clean', action='store_true',
          help='Force a clean ahead of the build')
  parser.add_option('-e', '--edit', action='store_true',
          help='Fix generated text files to use ${AM_DIR}')
  parser.add_option('-f', '--fresh', action='store_true',
          help='Regenerate data for current build from scratch')
  parser.add_option('-k', '--key', type='string',
          help='A key uniquely describing what was built')
  parser.add_option('-l', '--local-dir', type='string',
          help='Path of local directory')
  parser.add_option('-r', '--retry-fresh', action='store_true',
          help='On build failure, try a full fresh rebuild')

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
    audit = BuildAudit(dbdir=bldcmd.subdir)
  else:
    main([argv[0], "-h"])

  if bldcmd.dry_run:
    sys.exit(0)
  elif bldcmd.special_case:
    rc = bldcmd.execute_in(cwd)
    sys.exit(rc)

  key = options.key if options.key else bldcmd.tgtkey

  if options.clean:
    for tgt in audit.old_targets(key):
      try:
        os.remove(os.path.join(build_base, tgt))
      except OSError:
        pass

  if local_dir:
    if options.fresh:
      if os.path.exists(build_base):
        shutil.rmtree(build_base)
      os.makedirs(lwd)
      svnstat = ['svn', 'status', '--no-ignore']
      verbose(svnstat)
      svnstat = subprocess.Popen(svnstat, stdout=subprocess.PIPE, cwd=base_dir)
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
      copy_out_cmd = ['rsync', '-aC', '--include=core*', '--exclude-from=-']
    else:
      feed_to_rsync = audit.old_prereqs(key)
      copy_out_cmd = ['rsync', '-a', '--files-from=-']

    copy_out_cmd.extend([
        '--delete',
        '--delete-excluded',
        '--exclude=*.swp',
        '--exclude=' + os.path.basename(audit.dbfile),
        base_dir + os.sep,
        build_base])
    run_with_stdin(copy_out_cmd, feed_to_rsync)

    os.putenv('AM_DIR', local_dir)

  audit.get_reftime(lwd)

  rc = bldcmd.execute_in(lwd)

  if rc == 0:
    audit.update(key, build_base, options.fresh)
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

  return rc

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
