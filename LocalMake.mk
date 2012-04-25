Makefile ?= Makefile
MAKE := $(notdir $(MAKE))

ifneq (,$(and $(MLDIR),$(filter-out $(MLDIR)%,$(CURDIR))))
  _LocalCurDir := $(abspath $(MLDIR)/$(CURDIR))
  _LocalTreeBase := $(abspath $(MLDIR)/$(CURDIR)/$(BaseOfTree))
  _LocalMakeFlags := --no-print-directory -f $(Makefile)
  _LocalOverrides := $(filter-out MLDIR=% MLFLAGS=%,$(MAKEOVERRIDES))
  ifeq (,$(MAKECMDGOALS))
    .DEFAULT_GOAL = all
  endif
  %:: $(MAKEFILE_LIST)
    ifeq (clean,$(findstring clean,$(MAKECMDGOALS)))
	$(MAKE) $(_LocalMakeFlags) $(MAKECMDGOALS)
    else
	$(strip LocalMake -B $(BaseOfTree) -L $(MLDIR) $(MLFLAGS) -- \
	    $(MAKE) $(_LocalMakeFlags) $(_LocalOverrides) $(MAKECMDGOALS))
    endif
  $(MAKEFILE_LIST): ;
  .NOTPARALLEL:
else    	#MLDIR
  MAKEFILE_LIST :=
  include $(Makefile)
endif   	#MLDIR
