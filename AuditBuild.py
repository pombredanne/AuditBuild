#!/usr/bin/env python

import datetime
import fileinput
import optparse
import os
import re
import shared
import subprocess
import sys
import time

from auditutils import recreate_dir, verbose
from buildaudit import BuildAudit
from gmakecommand import GMakeCommand

def run_with_stdin(cmd, input):
  verbose(cmd)
  subproc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
  for line in input:
    print >> subproc.stdin, line
  subproc.stdin.close()
  if subproc.wait():
    sys.exit(2)

def main(argv):
  """Do an audited GNU make build, optionally copied to a different directory.

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
  msg += ' -b|--base-of-tree=DIR'
  msg += ' -c|--clean'
  msg += ' -e|--edit'
  msg += ' -f|--fresh'
  msg += ' -k|--key=KEY'
  msg += ' -p|--prebuild=COMMAND'
  msg += ' -q|--quiet'
  msg += ' -r|--retry-in-place'
  msg += ' -X|--execute-only'
  msg += ' -x|--external-dir=DIR'
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
  parser.add_option('-p', '--prebuild', type='string',
          default='test ! -d src/include || REUSE_VERSION=1 make -C src/include',
          help='A regexp matching files to be treated specially')
  parser.add_option('-q', '--quiet', action='store_true',
          help='Suppress common verbosity')
  parser.add_option('-r', '--retry-in-place', action='store_true',
          help='Retry failed external builds in the current directory')
  parser.add_option('-X', '--execute-only', action='store_true',
          help='Skip the auditing and just exec the build command')
  parser.add_option('-x', '--external-dir', type='string',
          help='Path of external directory')

  opts, left = parser.parse_args(argv[1:])
  if opts.edit and not opts.external_dir:
    parser.error("the --edit option makes no sense without --external-dir")

  shared.verbosity = 0 if opts.quiet else 1

  base_dir = os.path.abspath(opts.base_of_tree if opts.base_of_tree else '.')

  cwd = os.getcwd()

  bldcmd = GMakeCommand(left)

  if not bldcmd.argv:
    main([argv[0], "-h"])

  if opts.external_dir:
    external_dir = os.path.abspath(opts.external_dir)
    build_base = os.path.abspath(external_dir + os.sep + base_dir)
    bwd = os.path.abspath(external_dir + os.sep + cwd)
  else:
    external_dir = None
    build_base = base_dir
    bwd = cwd

  bldcmd.directory = bwd
  audit = BuildAudit(dbdir=bldcmd.subdir)

  if bldcmd.dry_run:
    sys.exit(0)
  elif bldcmd.special_case or opts.execute_only:
    rc = bldcmd.execute_in(bwd)
    sys.exit(rc)

  key = opts.key if opts.key else bldcmd.tgtkey

  if audit.has(key):
    if opts.clean:
      for tgt in audit.old_targets(key):
        try:
          os.remove(os.path.join(build_base, tgt))
        except OSError:
          pass
  else:
    opts.fresh = True

  if external_dir:
    if opts.fresh:
      recreate_dir(bwd)
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

    os.putenv('AB_DIR', external_dir)

  audit.setup(build_base)

  if opts.prebuild:
    print >> sys.stderr, '+', opts.prebuild
    rc = subprocess.call(opts.prebuild, shell=True, cwd=build_base, stdin=open(os.devnull))
    if (rc != 0):
      sys.exit(2)

  rc = bldcmd.execute_in(bwd)

  if rc != 0 and external_dir:
    if opts.retry_in_place:
      rc = bldcmd.execute_in(cwd)
      sys.exit(rc)
    elif not opts.fresh:
      nargv = argv[:]
      nargv.insert(1, '--fresh')
      verbose(nargv)
      rc = subprocess.call(nargv)
      sys.exit(rc)

  seconds = bldcmd.end_time - bldcmd.start_time
  bld_time = str(datetime.timedelta(seconds=int(seconds)))
  replace = opts.fresh and rc == 0
  audit.update(key, build_base, bld_time, replace)

  if external_dir:
    copy_back_cmd = ['rsync', '-a', build_base + os.sep, base_dir, '--files-from=-']
    if audit.new_targets:
      run_with_stdin(copy_back_cmd, audit.new_targets)
      if opts.edit:
        # TODO: better to write something like Perl's -T (text) test here
        tgts = [os.path.join(base_dir, t) for t in audit.new_targets if re.search(r'\.(cmd|depend|d|flags)$', t)]
        if tgts:
          mldir = external_dir + os.sep
          for line in fileinput.input(tgts, inplace=True):
            sys.stdout.write(line.replace(mldir, '/'))

  return rc

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
