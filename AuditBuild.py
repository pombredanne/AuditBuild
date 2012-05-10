#!/usr/bin/env python

import datetime
import fileinput
import optparse
import os
import re
import shutil
import subprocess
import sys
import time

from buildaudit import BuildAudit
from gmakecommand import GMakeCommand

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

  start_time = time.time()

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
          help='Fix generated text files to use ${AB_DIR}')
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

    os.putenv('AB_DIR', local_dir)

  if options.fresh:
    audit.prebuild(build_base)

  rc = bldcmd.execute_in(lwd)

  bldtime = ''
  if rc == 0:
    if options.fresh:
      audit.update(key, build_base, bldcmd.end_time - bldcmd.start_time)
      bldtime = " (build time: %s)" % (audit.bldtime(key))
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
    if audit.new_targets:
      run_with_stdin(copy_back_cmd, audit.new_targets)
      if options.edit:
        # TODO: better to write something like Perl's -T (text) test here
        tgts = [os.path.join(base_dir, t) for t in audit.new_targets if re.search(r'\.(cmd|depend|d|flags)$', t)]
        if tgts:
          mldir = local_dir + os.sep
          for line in fileinput.input(tgts, inplace=True):
            sys.stdout.write(line.replace(mldir, '/'))

  delta = int(time.time() - start_time + 0.5)
  elapsed = str(datetime.timedelta(seconds=delta))
  print "Elapsed: %s%s" % (elapsed, bldtime)

  return rc

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
