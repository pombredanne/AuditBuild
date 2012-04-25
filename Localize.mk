empty :=
space := $(empty) $(empty)
TGT := $(subst $(space),@,$(strip \
  $(sort $(filter-out LOCALBASE=%,$(MAKEOVERRIDES)))\
  $(sort $(or $(MAKECMDGOALS),all))))
#$(info =-= $(lastword $(MAKEFILE_LIST)): TGT='$(TGT)')

Makefile ?= Makefile

ifneq (,$(and $(LOCALBASE),$(filter-out $(LOCALBASE)%,$(CURDIR))))
_LocalDir := $(abspath $(LOCALBASE)/$(CURDIR))
_LocalMakeFlags := --no-print-directory -f $(Makefile) LOCALBASE=
_NFSTreeBase := $(abspath $(CURDIR)/$(BaseOfTree))
ifeq (clean,$(findstring clean,$(MAKECMDGOALS)))
  clean:: ; $(RM) -r $(_LocalDir)
  include $(Makefile)
else		#CLEAN
  .NOTPARALLEL:
  ifeq (,$(MAKECMDGOALS))
    .DEFAULT_GOAL = all
  endif
  %:: $(MAKEFILE_LIST)
	@mkdir -p $(_LocalDir)
	@rsync -aC --exclude='*.swp' --delete $(_NFSTreeBase)/ $(_LocalDir)
	@$(MAKE) $(_LocalMakeFlags) -C $(_LocalDir) $(MAKECMDGOALS)
	@rsync -a $(_LocalDir)/ $(_NFSTreeBase)
  $(MAKEFILE_LIST): ;
endif		#CLEAN
else    	#LOCALBASE
  MAKEFILE_LIST :=
  include $(Makefile)
endif   	#LOCALBASE
