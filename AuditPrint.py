#!/usr/bin/env python

import optparse
import os
import sys
from AuditMake import BuildAudit

def main(argv):
  """Read an AuditMake build audit and dump the data in
  various formats.

  """

  global prog
  prog = os.path.basename(argv[0])

  msg = prog
  msg += ' -d|--print-directories'
  msg += ' -i|--print-intermediates'
  msg += ' -k|--key'
  msg += ' -p|--print-prerequisites'
  msg += ' -s|--print-sparsefile'
  msg += ' -t|--print-targets'
  parser = optparse.OptionParser(usage=msg)
  parser.add_option('-d', '--print-directories', action='store_true',
          help='Print the list of directories containing prereqs for key')
  parser.add_option('-i', '--print-intermediates', action='store_true',
          help='Print the list of intermediates for the given key')
  parser.add_option('-k', '--key', type='string',
          help='A key uniquely describing what was built')
  parser.add_option('-p', '--print-prerequisites', action='store_true',
          help='Print the list of prerequisites for the given key')
  parser.add_option('-s', '--print-sparsefile', action='store_true',
          help='Print a ".sparse" file covering the set of prereqs')
  parser.add_option('-t', '--print-targets', action='store_true',
          help='Print the list of targets for the given key')
  options, left = parser.parse_args(argv[1:])
  if not options.key:
    main([argv[0], "-h"])

  audit = BuildAudit('.')
  audit.check(options.key)

  if options.print_directories or options.print_sparsefile:
    dirs = {}
    for f in audit.old_prereqs(options.key):
      d = os.path.dirname(f)
      dirs[d] = True
    if options.print_sparsefile:
      sys.stdout.write("[\n")
      for d in sorted(dirs):
        path = "'" + d + "/',"
        sys.stdout.write("   (%-*s  'files'),\n" % (60, path))
      sys.stdout.write("]\n")
    else:
      for d in sorted(dirs):
        print d

  if options.print_prerequisites:
    for f in sorted(audit.old_prereqs(options.key)):
      print f
  if options.print_intermediates:
    for f in sorted(audit.old_interms(options.key)):
      print f
  if options.print_targets:
    for f in sorted(audit.old_interms(options.key)):
      print f
    for f in sorted(audit.old_targets(options.key)):
      print f

  sys.exit(0)

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
