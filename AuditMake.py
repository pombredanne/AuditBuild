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
    (ignored_opts, survivors) = parse_ignored.parse_args(argv[1:])

    # Grab the flag that changes the actual build dir if present;
    # we'll need it.
    parse_dir = GMakeCommand.PassThroughOptionParser()
    parse_dir.add_option('-C', '--directory', type='string')
    (dir_opts, leftovers) = parse_dir.parse_args(survivors)
    self.directory = dir_opts.directory if dir_opts.directory else '.'

    # Look for the flags that mark this as a special case make,
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
    (special_opts, remains) = parse_spec.parse_args(leftovers)
    self.special = True if special_opts.set is not None else False

    makeflags = os.getenv('MAKEFLAGS', '')
    makeflags = re.sub(r'\s+--\s+.*', '', makeflags)
    makeflags = re.sub(r'\s*--\S+', '', makeflags)
    makeflags = re.sub(r'\S+=\S+', '', makeflags)
    if re.search(r'[BeIikLnopqRrStvW]', makeflags):
      self.special = True
    if re.search(r'[n]', makeflags):
      self.dry_run = True
    else:
      self.dry_run = False

    keys = []
    for word in remains:
      if re.match(r'(JOBS|PAR|V|VERBOSE|AM_DIR|AM_FLAGS)=', word):
        continue
      keys.append(word)

    self.key = '_'.join(sorted(keys))
    self.key = re.sub(os.sep, '@', self.key)
    if not self.key:
      self.key = 'DEFAULT'

  def get_argv(self):
    return self.argv

  def get_key(self):
    return self.key

  def get_directory(self):
    return self.directory

  def is_special_case(self):
    return self.special

  def is_dry_run(self):
    return self.dry_run

  def execute_in(self, dir):
    verbose(self.argv)
    retcode = subprocess.call(self.argv, cwd=dir)
    return retcode

class BuildAudit:
  """Class to manage and persist the audit of a build into prereqs and targets.

  The files used during a build can be categorized as prerequisites (read from)
  and targets (written to). Some are both, but a write beats a read so we treat
  any file modified as a target. This class manages a data structure
  categorizing the two sets. It also records the time delta for each file from
  start of build until last use.

  """
  def __init__(self, file, key, replace):
    self.file = file
    self.key = key
    try:
      json_fp = open(self.file, "r")
      self.db = json.load(json_fp)
      json_fp.close
    except IOError:
      self.db = {}
    if replace or not self.key in self.db:
      self.db[self.key] = {'PREREQS':{}, 'TARGETS':{}, 'ARGV':None}
    self.db[self.key]['ARGV'] = sys.argv
    self.prereqs = self.db[self.key]['PREREQS']
    self.targets = self.db[self.key]['TARGETS']
    self.prev_prereqs = self.prereqs.copy()
    self.prev_targets = self.targets.copy()

  def get_file(self):
    return self.file

  def add_prereq(self, path, delta):
    if not self.is_recorded(path):
      self.prereqs[path] = delta

  def add_target(self, path, delta):
    if not self.is_recorded(path):
      self.targets[path] = delta

  def get_prereqs(self):
    return self.prereqs

  def get_targets(self):
    return self.targets

  def is_recorded(self, path):
    if path in self.prereqs:
      return True
    elif path in self.targets:
      return True
    else:
      return False

  def dump(self):
    if any(True for k in self.prereqs if k not in self.prev_prereqs) or \
       any(True for k in self.targets if k not in self.prev_targets):
      print >> sys.stderr, "%s: updating database for '%s'" % (prog, self.key)
      fp = open(self.file, "w")
      json.dump(self.db, fp, indent=2)
      fp.write('\n');  # json does not add trailing newline
      fp.close

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
  last_time = ref_time = 0
  while True:
    fp = tempfile.TemporaryFile(dir=localdir)
    refstat = os.fstat(fp.fileno())
    this_time = refstat.st_mtime
    fp.close
    if last_time > 0:
      if ref_time > 0 and this_time > last_time:
        break
      elif this_time > last_time:
        ref_time = this_time
    last_time = this_time
    time.sleep(0.1)
  return ref_time

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
  required. The requirement is that the build filesystem update
  access times, i.e.  not be mounted with the "noatime" option. NFS
  mounts often employ "noatime" as an optimization.

  """

  global prog
  prog = os.path.basename(argv[0])

  msg = prog
  msg += ' -b|--base-of-tree <dir>'
  msg += ' -e|--edit'
  msg += ' -f|--fresh'
  msg += ' -k|--key'
  msg += ' -l|--local-dir <dir>'
  msg += ' -r|--retry-fresh'
  msg += ' -- gmake <gmake-args>...'
  parser = optparse.OptionParser(usage=msg)
  parser.add_option('-b', '--base-of-tree', type='string',
          help='Path to root of source tree (required)')
  parser.add_option('-e', '--edit', action='store_true',
          help='Fix generated text files to use ${AM_DIR}')
  parser.add_option('-f', '--fresh', action='store_true',
          help='Regenerate data for current build from scratch')
  parser.add_option('-k', '--key', type='string',
          help='Key uniquely describing what was built')
  parser.add_option('-l', '--local-dir', type='string',
          help='Path of local directory')
  parser.add_option('-r', '--retry-fresh', action='store_true',
          help='On build failure, try a full fresh rebuild')

  (options, left) = parser.parse_args(argv[1:])
  if len(left) == 0 or not options.base_of_tree:
    main([argv[0], "-h"])

  cwd = os.getcwd()

  gmake = GMakeCommand(left)

  if gmake.is_dry_run():
    sys.exit(0)
  elif gmake.is_special_case():
    rc = gmake.execute_in(cwd)
    sys.exit(rc)

  base_dir = os.path.abspath(options.base_of_tree)

  if options.local_dir:
    local_dir = os.path.abspath(options.local_dir)
    build_base = os.path.abspath(local_dir + os.sep + base_dir)
    lwd = os.path.abspath(local_dir + os.sep + cwd)
  else:
    local_dir = None
    build_base = base_dir
    lwd = cwd

  key = options.key if options.key else gmake.get_key()
  auditfile = os.path.join(gmake.get_directory(), 'BuildAudit.json')

  if local_dir:
    if not os.path.exists(lwd):
      options.fresh = True
    elif options.fresh:
      shutil.rmtree(build_base)

    audit = BuildAudit(auditfile, key, options.fresh)

    copy_out_cmd = ['rsync', '-aC', '--delete',
              '--exclude=*.swp',
              '--exclude=' + os.path.basename(audit.get_file()),
              base_dir + os.sep, build_base]
    if options.fresh:
      stat_cmd = ['svn', 'status', '--no-ignore']
      verbose(stat_cmd)
      svnstat = subprocess.Popen(stat_cmd, stdout=subprocess.PIPE, cwd=base_dir)
      privates = svnstat.communicate()[0]
      if svnstat.wait():
        sys.exit(2)
      os.makedirs(lwd)
      copy_out_cmd.insert(3, '--exclude-from=-')
      verbose(copy_out_cmd)
      rso = subprocess.Popen(copy_out_cmd, stdin=subprocess.PIPE)
      for line in privates.splitlines():
        rpath = re.sub(r'^[I?]\s+', '', line)
        if rpath == line:
          continue
        if re.search(r'vers\w*\.h$', rpath):
          continue
        apath = os.path.join(base_dir, rpath)
        if os.path.isdir(apath):
          rpath += os.sep
        print >> rso.stdin, rpath
      rso.stdin.close()
      if rso.wait():
        sys.exit(2)
    else:
      copy_out_cmd.insert(3, '--files-from=-')
      verbose(copy_out_cmd)
      rso = subprocess.Popen(copy_out_cmd, stdin=subprocess.PIPE)
      for prq in audit.get_prereqs():
        print >> rso.stdin, prq
      rso.stdin.close()
      if rso.wait():
        sys.exit(2)
    os.putenv('AM_DIR', local_dir)
  else:
    audit = BuildAudit(auditfile, key, options.fresh)

  reftime = get_ref_time(lwd)

  rc = gmake.execute_in(lwd)

  if rc == 0:
    updated_targets = []
    for parent, dir_names, file_names in os.walk(build_base):
      # Assume hidden dirs contain stuff we don't care about
      dir_names[:] = (dir_name for dir_name in dir_names if not dir_name.startswith('.'))

      for file_name in file_names:
        if file_name == os.path.basename(audit.get_file()):
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
          updated_targets.append(path)
        else:
          audit.add_prereq(rpath, adelta)
    audit.dump()
    if local_dir and options.edit:
      # TODO: it would be more general to implement a test for text files here.
      tgts = [t for t in updated_targets if re.search(r'\.(cmd|depend|d|flags)$', t)]
      mldir = local_dir + os.sep
      for line in fileinput.input(tgts, inplace=True):
        sys.stdout.write(re.sub(mldir, '${AM_DIR}/', line))
  elif options.retry_fresh and local_dir:
# TODO: --fresh and --retry-fresh should be marked incompatible.
    nargv = []
    for arg in argv:
      if not re.match(r'(-r|--retry)', arg):
        nargv.append(arg)
    nargv.insert(1, '--fresh')
    rc = subprocess.call(nargv)
    sys.exit(rc)

  if local_dir:
    copy_back_cmd = ['rsync', '-a', build_base + os.sep, base_dir, '--files-from=-']
    verbose(copy_back_cmd)
    rso = subprocess.Popen(copy_back_cmd, stdin=subprocess.PIPE)
    for tgt in audit.get_targets():
      print >> rso.stdin, tgt
    rso.stdin.close()
    if rso.wait():
      sys.exit(2)

  sys.exit(rc)

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=80:et:
