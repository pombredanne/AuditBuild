#!/usr/bin/env python

import datetime
import fileinput
import optparse
import os
import re
import shared
import shutil
import subprocess
import sys
import time

from buildaudit import BuildAudit
from gmakecommand import GMakeCommand
from auditutils import run_with_stdin, svn_export_dirs, svn_get_url, recreate_dir, verbose, svn_full_extract

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
  msg += ' -b|--base-of-tree <dir>'
  msg += ' -c|--clean'
  msg += ' -D|--dbname <file>'
  msg += ' -E|--extract-dirs-with-fallback <bom>'
  msg += ' -e|--edit'
  msg += ' -f|--fresh'
  msg += ' -k|--key <key>'
  msg += ' -p|--prebuild <command>'
  msg += ' -R|--remove-external-tree'
  msg += ' -r|--retry-in-place'
  msg += ' -U|--base-url <url>'
  msg += ' -v|--verbosity <n>'
  msg += ' -X|--execute-only'
  msg += ' -x|--external-dir <dir>'
  msg += ' -- gmake <gmake-args>...'
  parser = optparse.OptionParser(usage=msg)
  parser.add_option('-b', '--base-of-tree', type='string',
          help='Path to root of source tree')
  parser.add_option('-c', '--clean', action='store_true',
          help='Force a clean ahead of the build')
  parser.add_option('-D', '--dbname', type='string',
          help='Path to a database file')
  parser.add_option('-E', '--extract-dirs-with-fallback', type='string',
          help='Pre-populate the build tree from DB or BOM')
  parser.add_option('-e', '--edit', action='store_true',
          help='Fix up generated text files: s/<external-dir>//')
  parser.add_option('-f', '--fresh', action='store_true',
          help='Regenerate data for current build from scratch')
  parser.add_option('-k', '--key', type='string',
          help='A key uniquely describing what was built')
  parser.add_option('-p', '--prebuild', type='string', action='append',
          default=['test ! -d src/include || REUSE_VERSION=1 make -C src/include'],
          help='Setup command(s) to be run prior to the build proper')
  parser.add_option('-R', '--remove-external-tree', action='store_true',
          help='Remove the external build tree before exiting')
  parser.add_option('-r', '--retry-in-place', action='store_true',
          help='Retry failed external builds in the current directory')
  parser.add_option('-U', '--base-url', type='string',
          help='The svn URL from which to get files')
  parser.add_option('-v', '--verbosity', type='int',
          help='Change the amount of verbosity')
  parser.add_option('-X', '--execute-only', action='store_true',
          help='Skip the auditing and just exec the build command')
  parser.add_option('-x', '--external-dir', type='string',
          help='Path of external directory')

  opts, left = parser.parse_args(argv[1:])
  if opts.edit and not opts.external_dir:
    parser.error("the --edit option makes no sense without --external-dir")
  if not left:
    main([argv[0], "-h"])

  shared.verbosity = opts.verbosity if opts.verbosity is not None else 1

  base_dir = os.path.abspath(opts.base_of_tree if opts.base_of_tree else '.')

  cwd = os.getcwd()

  if opts.external_dir:
    external_dir = os.path.abspath(opts.external_dir)
    build_base = os.path.abspath(external_dir + os.sep + base_dir)
    bwd = os.path.abspath(external_dir + os.sep + cwd)
  else:
    external_dir = None
    build_base = base_dir
    bwd = cwd

  bldcmd = GMakeCommand(left)
  bldcmd.directory = bwd

  if opts.dbname:
    audit = BuildAudit(opts.dbname)
  else:
    audit = BuildAudit(dbdir=bldcmd.subdir)

  key = opts.key if opts.key else bldcmd.tgtkey

  base_url = opts.base_url if opts.base_url else audit.baseurl(key)
  if not base_url:
    base_url = svn_get_url(base_dir)

  if opts.extract_dirs_with_fallback:
    rc = svn_export_dirs(base_url, base_dir, audit.old_prereqs([key]))
    if rc != 0:
      exfile = os.path.join(base_url, opts.extract_dirs_with_fallback)
      rc = svn_full_extract(exfile, base_dir)
      if rc != 0:
        sys.exit(2)

  if bldcmd.dry_run:
    sys.exit(0)
  elif bldcmd.special_case or opts.execute_only:
    rc = bldcmd.execute_in(cwd)
    sys.exit(rc)

  if audit.has(key):
    if opts.clean:
      for tgt in audit.old_targets([key]):
        try:
          os.remove(os.path.join(build_base, tgt))
        except OSError:
          pass
  else:
    opts.fresh = True

  if external_dir:
    copy_out_cmd = ['rsync', '-a']
    if opts.fresh:
      copy_out_cmd.append('--exclude=[.]svn*')
      recreate_dir(bwd)
      feed_to_rsync = []
      if False:
        svnstat = ['svn', 'status', '--no-ignore']
        verbose(svnstat)
        svnstat = subprocess.Popen(svnstat, cwd=base_dir, stdout=subprocess.PIPE, stderr=open(os.devnull))
        privates = svnstat.communicate()[0]
        if svnstat.returncode != 0:
          sys.exit(2)
        for line in privates.splitlines():
          rpath = re.sub(r'^[I?]\s+', '', line)
          if rpath == line:
            continue
          if os.path.isdir(os.path.join(base_dir, rpath)):
            rpath += os.sep
          feed_to_rsync.append(rpath)
        copy_out_cmd.append('--exclude-from=-')
    else:
      if not os.path.exists(build_base):
        os.makedirs(build_base)
      feed_to_rsync = audit.old_prereqs([key])
      copy_out_cmd = ['rsync', '-a', '--files-from=-']

    copy_out_cmd.extend([
        '--delete',
        '--delete-excluded',
        '--exclude=*.swp',
        '--exclude=' + os.path.basename(audit.dbfile),
        base_dir + os.sep,
        build_base])
    run_with_stdin(copy_out_cmd, feed_to_rsync)

  audit.setup(build_base)

  if opts.prebuild:
    for cmd in opts.prebuild:
      verbose([cmd])
      rc = subprocess.call(cmd, shell=True, cwd=build_base, stdin=open(os.devnull))
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
  audit.update(key, build_base, bld_time, base_url, replace)

  if external_dir:
    if audit.new_targets:
      copy_in_cmd = ['rsync', '-a', build_base + os.sep, base_dir, '--files-from=-']
      run_with_stdin(copy_in_cmd, audit.new_targets)
      if opts.edit:
        # TODO: better to write something like Perl's -T (text) test here
        tgts = [os.path.join(base_dir, t) for t in audit.new_targets if re.search(r'\.(cmd|depend|d|flags)$', t)]
        if tgts:
          mldir = external_dir + os.sep
          for line in fileinput.input(tgts, inplace=True):
            sys.stdout.write(line.replace(mldir, '/'))
    if opts.remove_external_tree:
      verbose("Removing %s/..." % (build_base))
      shutil.rmtree(build_base)

  return rc

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
