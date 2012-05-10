#!/usr/bin/env python

import optparse
import os
import sys
import warnings

from buildaudit import BuildAudit

def main(argv):
  """Read a build audit and dump the data in various formats."""

  prog = os.path.basename(argv[0])

  def key_callback(option, opt, value, parser):
    setattr(parser.values, option.dest, value.split(','))

  msg = '%prog'
  msg += ' -a|--print-all'
  msg += ' -b|--build-time'
  msg += ' -d|--print-directories'
  msg += ' -f|--dbname <file>'
  msg += ' -I|--print-intermediates'
  msg += ' -k|--keys <key,key,...>'
  msg += ' -l|--list-keys'
  msg += ' -p|--print-prerequisites'
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
  parser.add_option('-f', '--dbname', type='string', default='.',
          help='Path to a database file')
  parser.add_option('-I', '--print-intermediates', action='store_true',
          help='Print intermediates for the given key(s)')
  parser.add_option('-k', '--keys', type='string',
          action='callback', callback=key_callback,
          help='Comma-separated list of keys')
  parser.add_option('-l', '--list-keys', action='store_true',
          help='List all known keys in the given database')
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
  options, left = parser.parse_args(argv[1:])

  audit = BuildAudit(options.dbname)

  if options.keys:
    keylist = options.keys
  else:
    keylist = audit.all_keys()

  if options.list_keys:
    for k in keylist:
      print k
    sys.exit(0)

  if not (options.print_directories or options.print_sparsefile or
          options.print_prerequisites or options.print_intermediates or
          options.print_terminal_targets or options.print_targets or
          options.print_all or options.print_unused or options.build_time):
    main([argv[0], "-h"])

  results = {}
  for key in keylist:
    if not audit.has(key):
      print >> sys.stderr, "%s: Error: no such key: %s" % (prog, key)
      continue

    if options.print_directories or options.print_sparsefile:
      dirs = {}
      for prq in audit.old_prereqs(key):
        dir = os.path.dirname(prq)
        results[dir] = True
    elif options.build_time:
      print "%s: %s" % (key, audit.bldtime(key))
      continue
    else:
      if options.print_prerequisites:
        results.update(audit.old_prereqs(key))
      if options.print_intermediates:
        results.update(audit.old_intermediates(key))
      if options.print_terminal_targets:
        results.update(audit.old_terminals(key))
      if options.print_targets:
        results.update(audit.old_targets(key))
      if options.print_all:
        results.update(audit.old_prereqs(key))
        results.update(audit.old_targets(key))
      if options.print_unused:
        results.update(audit.old_unused(key))

  if options.print_sparsefile:
    print '#', options.print_sparsefile
    print '['
    print "   (%-*s  'files')," % (60, "'./',")
    for d in sorted(results):
      path = "'" + d + "/',"
      print "   (%-*s  'files')," % (60, path)
    print ']'
  else:
    for line in sorted(results):
      print line

  return 0

if '__main__' == __name__:
  sys.exit(main(sys.argv))

# vim: ts=8:sw=2:tw=120:et:
