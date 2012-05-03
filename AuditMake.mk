Makefile ?= Makefile
MAKE := $(notdir $(MAKE))

ifneq (,$(and $(AM_DIR),$(filter-out $(AM_DIR)%,$(CURDIR))))
  _AuditMakeFlags := --no-print-directory -f $(Makefile)
  _AuditOverrides := $(filter-out AM_DIR=% AM_FLAGS=%,$(MAKEOVERRIDES))
  ifeq (,$(MAKECMDGOALS))
    .DEFAULT_GOAL = all
  endif
  %:: $(MAKEFILE_LIST)
    ifeq (clean,$(findstring clean,$(MAKECMDGOALS)))
	$(MAKE) $(_AuditMakeFlags) $(MAKECMDGOALS)
    else
	$(strip AuditMake -b $(BaseOfTree) -l $(AM_DIR) $(AM_FLAGS) -- \
	    $(MAKE) $(_AuditMakeFlags) $(_AuditOverrides) $(MAKECMDGOALS))
    endif
  $(MAKEFILE_LIST): ;
  .NOTPARALLEL:
else    	#AM_DIR
  MAKEFILE_LIST :=
  include $(Makefile)
endif   	#AM_DIR
