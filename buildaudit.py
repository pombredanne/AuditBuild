import datetime
import json
import os
import sys
import tempfile
import time
import warnings

class BuildAudit:
  """Class to manage and persist the audit of a build into prereqs and targets.

  Files used during a build can be categorized as prerequisites
  (read from) and targets (written to). Targets may also be read
  from (think of a .o file which is then linked into a program)
  so these actually break down into "intermediate" and "terminal"
  targets.  This class manages a data structure categorizing
  these file sets.

  """
  def __init__(self, dbdir='.', dbname='BuildAudit.json'):
    self.dbfile = os.path.join(dbdir, dbname)
    try:
      self.db = json.load(open(self.dbfile))
    except IOError:
      self.db = {}
    self.new_targets = {}

  def has(self, key):
    return key in self.db

  def all_keys(self):
    return sorted(self.db.keys())

  def old_prereqs(self, key):
    return self.db[key]['PREREQS'] if key in self.db else {}

  def old_intermediates(self, key):
    return self.db[key]['INTERMEDIATES'] if key in self.db else {}

  def old_terminals(self, key):
    return self.db[key]['TERMINALS'] if key in self.db else {}

  def old_unused(self, key):
    return self.db[key]['UNUSED'] if key in self.db else {}

  def old_targets(self, key):
    both = {}
    both.update(self.old_intermediates(key))
    both.update(self.old_terminals(key))
    return both

  def bldtime(self, key):
    return self.db[key]['BLDTIME']

  def prebuild(self, indir):
    """Set a unique file reference time and prepare for the build.

    Different filesystems have different granularities for time
    stamps. For instance, ext3 records one-second granularity while
    ext4 records nanoseconds. Regardless of host filesystem, this
    method guarantees to return a timestamp value newer than any
    file previously accessed within the same filesystem and same
    thread, and no newer than any timestamp created subsequently.

    """

    # There are some builds which touch their prerequisites,
    # causing them to look like targets. To protect against
    # that we use the belt-and-suspenders approach of checking
    # against a list of files which predated the build.
    self.pre_existing = {}
    for parent, dir_names, file_names in os.walk(indir):
      # Assume hidden dirs contain stuff we don't care about
      dir_names[:] = (d for d in dir_names if not d.startswith('.'))
      for file_name in file_names:
        rpath = os.path.relpath(os.path.join(parent, file_name), indir)
        self.pre_existing[rpath] = True

    def get_time_past(previous):
      this_time = 0
      while True:
        with tempfile.TemporaryFile(dir=indir) as fp:
          this_time = os.fstat(fp.fileno()).st_mtime
        if this_time > previous:
          break
        time.sleep(0.1)
      return this_time

    old_time = get_time_past(0)
    self.reftime = get_time_past(old_time)

  def update(self, key, basedir, seconds):
    prereqs = {}
    intermediates = {}
    terminals = {}
    unused = {}
    # Note: do NOT use os.walk here.
    # It has a way of updating symlink atimes.
    def visit(data, parent, files):
      # Assume hidden dirs contain stuff we don't care about
      if not parent.startswith('.'):
        for f in files:
          path = os.path.join(parent, f)
          if not os.path.isdir(path):
            rpath = os.path.relpath(path, basedir)
            stats = os.lstat(path)
            adelta = stats.st_atime - self.reftime
            mdelta = stats.st_mtime - self.reftime
            if mdelta >= 0:
              if adelta >= 0 and rpath in self.pre_existing:
                prereqs[rpath] = 'P'
              elif adelta > mdelta:
                intermediates[rpath] = 'I'
              else:
                terminals[rpath] = 'T'
            elif adelta >= 0:
              prereqs[rpath] = 'P'
            else:
              unused[rpath] = 'U'
    os.path.walk(basedir, visit, None)

    self.new_targets.update(intermediates)
    self.new_targets.update(terminals)

    if not prereqs:
      warnings.warn("Empty prereq set - check for 'noatime' mount")
    else:
      refstr = "%s (%s)" % (str(self.reftime), time.ctime(self.reftime))
      bldtime = str(datetime.timedelta(seconds=int(seconds)))
      self.db[key] = {'PREREQS': prereqs,
                      'INTERMEDIATES': intermediates,
                      'TERMINALS': terminals,
                      'UNUSED': unused,
                      'CMDLINE': sys.argv,
                      'REFTIME': refstr,
                      'BLDTIME': bldtime}
      print >> sys.stderr, "updating database for '%s'" % (key)
      with open(self.dbfile, "w") as fp:
        json.dump(self.db, fp, indent=2)
        fp.write('\n');  # json does not add trailing newline

# vim: ts=8:sw=2:tw=120:et:
