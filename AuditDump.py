#!/usr/bin/env python

import shared
import optparse
import os
import re
import subprocess
import sys
import warnings

from auditutils import recreate_dir, verbose
from buildaudit import BuildAudit

def dirnames(files):
  dirs = {}
  for f in files:
    d = os.path.dirname(f)
    dirs[d] = True
  return dirs

def main(argv):
  """Read a build audit and dump the data in various formats."""

  prog = os.path.basename(argv[0])

  def key_callback(option, opt, value, parser):
    setattr(parser.values, option.dest, value.split(','))

  msg = '%prog'
  msg += ' -a|--print-all'
  msg += ' -b|--build-time'
  msg += ' -d|--print-directories'
  msg += ' -E|--svn-export-dirs <dir>'
  msg += ' -e|--svn-export <dir>'
  msg += ' -f|--dbname <file>'
  msg += ' -I|--print-intermediates'
  msg += ' -k|--keys <key,key,...>'
  msg += ' -l|--list-keys'
  msg += ' -p|--print-prerequisites'
  msg += ' -q|--quiet'
  msg += ' -s|--print-sparsefile <comment>'
  msg += ' -T|--print-terminal-targets'
  msg += ' -t|--print-targets'
  msg += ' -u|--print-unused'
  parser = optparse.OptionParser(usage=msg)
  parser.add_option('-a', '--print-all', action='store_true',
          help='Print all involved files for key(s)')
  parser.add_option('-b', '--build-time', action='store_true',
          help='Print the elapsed time of the specified build(s)')
  parser.add_option('-d', '--print-directories', action='store_true',
          help='Print directories containing prereqs for key(s)')
  parser.add_option('-E', '--svn-export-dirs', type='string',
          help='Build a tree containing all files from prerequisite dirs in DIR')
  parser.add_option('-e', '--svn-export', type='string',
          help='Build a tree containing just the prerequisites in DIR')
  parser.add_option('-f', '--dbname', type='string',
          help='Path to a database file')
  parser.add_option('-I', '--print-intermediates', action='store_true',
          help='Print intermediates for the given key(s)')
  parser.add_option('-k', '--keys', type='string',
          action='callback', callback=key_callback,
          help='Comma-separated list of keys')
  parser.add_option('-l', '--list-keys', action='store_true',
          help='List all known keys in the given database')
  parser.add_option('-q', '--quiet', action='store_true',
          help='Suppress common verbosity')
  parser.add_option('-p', '--print-prerequisites', action='store_true',
          help='Print prerequisites for the given key(s)')
  parser.add_option('-s', '--print-sparsefile', type='string',
          help='Print a ".sparse" file covering the set of prereqs')
  parser.add_option('-T', '--print-terminal-targets', action='store_true',
          help='Print terminal targets for the given key(s)')
  parser.add_option('-t', '--print-targets', action='store_true',
          help='Print targets for the given key(s)')
  parser.add_option('-u', '--print-unused', action='store_true',
          help='Print files present but unused for key(s)')
  opts, left = parser.parse_args(argv[1:])

  if not [o for o in vars(opts) if opts.__dict__[o]]:
    main([argv[0], "-h"])

  shared.verbosity = 0 if opts.quiet else 1

  rc = 0

  if opts.dbname:
    audit = BuildAudit(opts.dbname)
  else:
    audit = BuildAudit()

  if opts.keys:
    keylist = opts.keys
  else:
    keylist = audit.all_keys()
    print >> sys.stderr, "Using keys: %s" % (keylist)

  if opts.list_keys:
    for k in keylist:
      print k
    sys.exit(0)

  results = {}
  for key in keylist:
    if not audit.has(key):
      print >> sys.stderr, "%s: Error: no such key: %s" % (prog, key)
      rc = 2
      continue

    if opts.build_time:
      print "%s: %s" % (key, audit.bldtime(key))
      continue
    elif opts.print_sparsefile or opts.svn_export:
      results.update(audit.old_prereqs(key))
    elif opts.svn_export_dirs:
      results.update(dirnames(audit.old_prereqs(key)))
    else:
      if opts.print_directories:
        results.update(dirnames(audit.old_prereqs(key)))
      if opts.print_prerequisites:
        results.update(audit.old_prereqs(key))
      if opts.print_intermediates:
        results.update(audit.old_intermediates(key))
      if opts.print_terminal_targets:
        results.update(audit.old_terminals(key))
      if opts.print_targets:
        results.update(audit.old_targets(key))
      if opts.print_all:
        results.update(audit.old_prereqs(key))
        results.update(audit.old_targets(key))
      if opts.print_unused:
        results.update(audit.old_unused(key))

  if opts.print_sparsefile:
    print '#', opts.print_sparsefile
    print '['
    print "   (%-*s  'files')," % (60, "'./',")
    for d in sorted(dirnames(results)):
      path = "'" + d + "/',"
      print "   (%-*s  'files')," % (60, path)
    print ']'
  if opts.svn_export_dirs:
    base = recreate_dir(opts.svn_export_dirs)
    for d in sorted(results):
      to = os.path.join(base, d)
      parent = os.path.dirname(to)
      if not os.path.exists(parent):
        os.makedirs(parent)
      cmd = ['svn', 'export', '--quiet', '--depth', 'files', d, to]
      verbose(cmd)
      if subprocess.call(cmd) != 0:
        rc = 2
  elif opts.svn_export:
    base = recreate_dir(opts.svn_export)
    for d in sorted(dirnames(results)):
      dir = os.path.join(base, d)
      if not os.path.exists(dir):
        os.makedirs(dir)
    for f in results:
      cmd = ['svn', 'export', '--quiet', f, os.path.join(base, f)]
      verbose(cmd)
      if subprocess.call(cmd) != 0:
        rc = 2
  else:
    for line in sorted(results):
      print line

  return rc

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
