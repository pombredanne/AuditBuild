import datetime
import json
import os
import re
import sys
import tempfile
import time
import warnings

from auditutils import verbose

class BuildAudit:
  """Class to manage and persist the audit of a build into prereqs and targets.

  Files used during a build can be categorized as prerequisites
  (read from) and targets (written to). Targets may also be read
  from (think of a .o file which is then linked into a program)
  so these actually break down into "intermediate" and "terminal"
  targets.  This class manages a data structure categorizing
  these file sets.

  """
  def __init__(self, dbname='BuildAudit.json', dbdir=None):
    if dbdir:
      self.dbfile = os.path.join(dbdir, dbname)
    else:
      self.dbfile = dbname

    try:
      self.db = json.load(open(self.dbfile))
    except IOError:
      self.db = {}

    self.new_targets = {}

  def has(self, key):
    return key in self.db

  def all_keys(self):
    return sorted(self.db.keys())

  def old_data(self, keys, category):
    results = {}
    for key in keys:
      if key in self.db:
        results.update(self.db[key][category])
    return results

  def old_prereqs(self, keys):
    return self.old_data(keys, 'PREREQS')

  def old_intermediates(self, keys):
    return self.old_data(keys, 'INTERMEDIATES')

  def old_terminals(self, keys):
    return self.old_data(keys, 'TERMINALS')

  def old_unused(self, keys):
    return self.old_data(keys, 'UNUSED')

  def old_targets(self, keys):
    both = {}
    both.update(self.old_intermediates(keys))
    both.update(self.old_terminals(keys))
    return both

  def bldtime(self, key):
    return self.db[key]['COMMENT']['BLDTIME']

  def baseurl(self, key):
    return self.db[key]['COMMENT']['BASEURL'] if key in self.db else None

  def setup(self, indir):
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
      dir_names[:] = (dn for dn in dir_names if not dn.startswith('.svn'))
      for file_name in file_names:
        rpath = os.path.relpath(os.path.join(parent, file_name), indir)
        self.pre_existing[rpath] = True

    self.ref_file = '.audit-ref.tmp'
    ref = os.path.join(indir, self.ref_file)

    def get_time_past(previous):
      this_mtime = this_atime = 0
      while True:
        with open(ref, "w+") as fp:
          stats = os.fstat(fp.fileno())
          this_mtime = stats.st_mtime
          this_atime = stats.st_atime
        if this_mtime > previous:
          break
        else:
          os.remove(ref)
        time.sleep(0.1)
      return this_mtime, this_atime

    mtime1, atime1 = get_time_past(0)
    mtime2, atime2 = get_time_past(mtime1)
    if atime2 > atime1:
      self.reftime = mtime2
    else:
      self.reftime = -1
      os.remove(ref)

  def noatime(self):
    return self.reftime == -1

  def update(self, key, basedir, bldtime, baseurl, replace):
    prereqs = {}
    intermediates = {}
    terminals = {}
    unused = {}
    # Note: do NOT use os.walk here.
    # It has a way of updating symlink atimes.
    def visit(data, parent, files):
      if not parent.startswith('.svn'):
        for fn in files:
          if fn == self.ref_file:
            continue
          path = os.path.join(parent, fn)
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
            elif adelta >= 0 and rpath in self.pre_existing:
              prereqs[rpath] = 'P'
            else:
              unused[rpath] = 'U'
    os.path.walk(basedir, visit, None)

    self.new_targets.update(intermediates)
    self.new_targets.update(terminals)

    if not prereqs:
      warnings.warn("empty prereq set - check for 'noatime' mount")
    elif replace:
      refstr = "%s (%s)" % (str(self.reftime), time.ctime(self.reftime))
      self.db[key] = {
                      'PREREQS': prereqs,
                      'INTERMEDIATES': intermediates,
                      'TERMINALS': terminals,
                      'UNUSED': unused,
                      'COMMENT': {
                        'BLDTIME': bldtime,
                        'CMDLINE': sys.argv,
                        'REFTIME': refstr,
                        'BASEURL': baseurl,
                        }
                     }
      verbose("Updating database for '%s'" % (key))
      with open(self.dbfile, "w") as fp:
        json.dump(self.db, fp, indent=2)
        fp.write('\n');  # json does not add trailing newline

# vim: ts=8:sw=2:tw=120:et:
