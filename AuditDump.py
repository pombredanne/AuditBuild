#!/usr/bin/env python

import argparse
import os
import re
import subprocess
import sys

import shared
from auditutils import recreate_dir, verbose, dirnames, svn_export_files, svn_export_dirs
from buildaudit import BuildAudit

def main(argv):
  """Read a build audit and dump the data in various formats."""

  prog = os.path.basename(argv[0])

  parser = argparse.ArgumentParser()
  parser.add_argument('-a', '--print-all', action='store_true',
          help='Print all involved files for key(s)')
  parser.add_argument('-b', '--build-time', action='store_true',
          help='Print the elapsed time of the specified build(s)')
  parser.add_argument('-D', '--dbname',
          help='Path to a database file')
  parser.add_argument('-d', '--print-directories', action='store_true',
          help='Print directories containing prereqs for key(s)')
  parser.add_argument('-E', '--svn-export-dirs',
          help='Build a tree containing all files from prerequisite dirs in DIR')
  parser.add_argument('-e', '--svn-export-files',
          help='Build a tree containing just the prerequisites in DIR')
  parser.add_argument('-I', '--print-intermediates', action='store_true',
          help='Print intermediates for the given key(s)')
  parser.add_argument('-k', '--keys', action='append',
          help='List of keys to query')
  parser.add_argument('-l', '--list-keys', action='store_true',
          help='List all known keys in the given database')
  parser.add_argument('-p', '--print-prerequisites', action='store_true',
          help='Print prerequisites for the given key(s)')
  parser.add_argument('-s', '--print-sparse-file',
          help='Print a ".sparse" file covering the set of prereqs')
  parser.add_argument('-T', '--print-terminal-targets', action='store_true',
          help='Print terminal targets for the given key(s)')
  parser.add_argument('-t', '--print-targets', action='store_true',
          help='Print all targets for the given key(s)')
  parser.add_argument('-u', '--print-unused', action='store_true',
          help='Print files present but unused for key(s)')
  parser.add_argument('-v', '--verbosity', type=int,
          help='Change the amount of verbosity')
  opts = parser.parse_args(argv[1:])

  if (len(argv) < 2):
    main([argv[0], "-h"])

  if not [o for o in vars(opts) if opts.__dict__[o] is not None]:
    main([argv[0], "-h"])

  shared.verbosity = opts.verbosity if opts.verbosity is not None else 1

  rc = 0

  if opts.dbname:
    audit = BuildAudit(opts.dbname)
  else:
    audit = BuildAudit()

  # Check that a database was found
  with open(audit.dbfile):
    pass

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
  elif opts.print_sparse_file is not None:
    if len(opts.print_sparse_file) > 0:
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
  try:
    rc = main(sys.argv)
  except IOError as e:
    # Workaround for an interpreter bug triggered by SIGPIPE.
    # See http://code.activestate.com/lists/python-tutor/88460/
    if "Broken pipe" in e.strerror:
      rc = 0
    else:
      raise

  sys.exit(rc)

# vim: ts=8:sw=2:tw=120:et:
