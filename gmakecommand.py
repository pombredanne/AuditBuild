import atexit
import datetime
import optparse
import os
import re
import sys
import subprocess
import time

import shared
from auditutils import recreate_dir, verbose

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

    assignments = []
    tgts = []
    for word in remains:
      if '=' in word:
        assignments.append(word)
      else:
        tgts.append(word)

    assigns = []
    for word in assignments:
      if not re.match(r'(JOBS|PAR|V|VERBOSE|AB_DIR|AB_FLAGS)=', word):
        assigns.append(word)
    self.tgtkey = '__'.join(sorted(assigns))
    if self.tgtkey:
      self.tgtkey += ';'
    if tgts:
      self.tgtkey += ':'.join(sorted(tgts))
    else:
      self.tgtkey += 'all'  #just by convention

  def printstats(self):
    if shared.verbosity > 0:
      b = int(self.end_time - self.start_time + 0.5)
      bldstr = str(datetime.timedelta(seconds=b))
      e = int(time.time() - self.start_time + 0.5)
      elapsed = str(datetime.timedelta(seconds=e))
      print >> sys.stderr, "Elapsed: %s (build time: %s)" % (elapsed, bldstr)

  def execute_in(self, dir):
    verbose(self.argv)
    self.start_time = time.time()
    rc = subprocess.call(self.argv, cwd=dir, stdin=open(os.devnull))
    self.end_time = time.time()
    atexit.register(GMakeCommand.printstats, self)
    return rc

# vim: ts=8:sw=2:tw=120:et:
