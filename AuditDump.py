#!/usr/bin/env python

import optparse
import os
import re
import subprocess
import sys
import warnings

import shared
from auditutils import recreate_dir, verbose, dirnames, svn_export_files, svn_export_dirs
from buildaudit import BuildAudit

def main(argv):
  """Read a build audit and dump the data in various formats."""

  prog = os.path.basename(argv[0])

  def key_callback(option, opt, value, parser):
    setattr(parser.values, option.dest, value.split(','))

  msg = '%prog'
  msg += ' -a|--print-all'
  msg += ' -b|--build-time'
  msg += ' -D|--dbname <file>'
  msg += ' -d|--print-directories'
  msg += ' -E|--svn-export-dirs <dir>'
  msg += ' -e|--svn-export-files <dir>'
  msg += ' -I|--print-intermediates'
  msg += ' -k|--keys <key,key,...>'
  msg += ' -l|--list-keys'
  msg += ' -p|--print-prerequisites'
  msg += ' -s|--print-sparse-file <comment>'
  msg += ' -T|--print-terminal-targets'
  msg += ' -t|--print-targets'
  msg += ' -u|--print-unused'
  msg += ' -v|--verbosity <n>'
  parser = optparse.OptionParser(usage=msg)
  parser.add_option('-a', '--print-all', action='store_true',
          help='Print all involved files for key(s)')
  parser.add_option('-b', '--build-time', action='store_true',
          help='Print the elapsed time of the specified build(s)')
  parser.add_option('-D', '--dbname', type='string',
          help='Path to a database file')
  parser.add_option('-d', '--print-directories', action='store_true',
          help='Print directories containing prereqs for key(s)')
  parser.add_option('-E', '--svn-export-dirs', type='string',
          help='Build a tree containing all files from prerequisite dirs in DIR')
  parser.add_option('-e', '--svn-export-files', type='string',
          help='Build a tree containing just the prerequisites in DIR')
  parser.add_option('-I', '--print-intermediates', action='store_true',
          help='Print intermediates for the given key(s)')
  parser.add_option('-k', '--keys', type='string',
          action='callback', callback=key_callback,
          help='Comma-separated list of keys')
  parser.add_option('-l', '--list-keys', action='store_true',
          help='List all known keys in the given database')
  parser.add_option('-p', '--print-prerequisites', action='store_true',
          help='Print prerequisites for the given key(s)')
  parser.add_option('-s', '--print-sparse-file', type='string',
          help='Print a ".sparse" file covering the set of prereqs')
  parser.add_option('-T', '--print-terminal-targets', action='store_true',
          help='Print terminal targets for the given key(s)')
  parser.add_option('-t', '--print-targets', action='store_true',
          help='Print targets for the given key(s)')
  parser.add_option('-u', '--print-unused', action='store_true',
          help='Print files present but unused for key(s)')
  parser.add_option('-v', '--verbosity', type='int',
          help='Change the amount of verbosity')
  opts, left = parser.parse_args(argv[1:])

  if not [o for o in vars(opts) if opts.__dict__[o]]:
    main([argv[0], "-h"])

  shared.verbosity = opts.verbosity if opts.verbosity is not None else 1

  rc = 0

  if opts.dbname:
    audit = BuildAudit(opts.dbname)
  else:
    audit = BuildAudit()

  if opts.keys:
    keylist = opts.keys
    for key in keylist:
      if not audit.has(key):
        print >> sys.stderr, "%s: Error: no such key: %s" % (prog, key)
        sys.exit(2)
  else:
    keylist = audit.all_keys()
    if opts.list_keys:
      for key in keylist:
        print key
      sys.exit(0)
    else:
      verbose("Using keys: %s" % (keylist))
      if not keylist:
        sys.exit(2)

  if opts.build_time:
    for key in keylist:
      print "%s: %s" % (key, audit.bldtime(key))
  elif opts.print_sparse_file:
    print '#', opts.print_sparse_file
    print '['
    print "   (%-*s  'files')," % (60, "'./',")
    for dir in sorted(dirnames(audit.old_prereqs(keylist))):
      path = "'" + dir + "/',"
      print "   (%-*s  'files')," % (60, path)
    print ']'
  elif opts.svn_export_dirs:
    rc = svn_export_dirs(audit.baseurl(keylist[0]), opts.svn_export_dirs, audit.old_prereqs(keylist))
  elif opts.svn_export_files:
    rc = svn_export_files(audit.baseurl(keylist[0]), opts.svn_export_files, audit.old_prereqs(keylist))
  elif opts.print_directories:
    for line in sorted(dirnames(audit.old_prereqs(keylist))):
      print line
  else:
    results = {}
    if opts.print_prerequisites:
      results.update(audit.old_prereqs(keylist))
    if opts.print_intermediates:
      results.update(audit.old_intermediates(keylist))
    if opts.print_terminal_targets:
      results.update(audit.old_terminals(keylist))
    if opts.print_targets:
      results.update(audit.old_targets(keylist))
    if opts.print_all:
      results.update(audit.old_prereqs(keylist))
      results.update(audit.old_targets(keylist))
    if opts.print_unused:
      results.update(audit.old_unused(keylist))
    for line in sorted(results):
      print line

  return rc

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
