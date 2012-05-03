Makefile ?= Makefile
MAKE := $(notdir $(MAKE))

ifneq (,$(filter AM_%,$(MAKEOVERRIDES)))
  _AuditMakeFlags := --no-print-directory -f $(Makefile)
  _AuditOverrides := $(filter-out AM_%,$(MAKEOVERRIDES))
  ifeq (,$(MAKECMDGOALS))
    .DEFAULT_GOAL = all
  endif
  %:: $(MAKEFILE_LIST)
    ifeq (clean,$(findstring clean,$(MAKECMDGOALS)))
	$(MAKE) $(_AuditMakeFlags) $(MAKECMDGOALS)
    else
	$(strip AuditMake -b $(BaseOfTree) $(if $(AM_DIR),-l $(AM_DIR)) $(AM_FLAGS) -- \
		$(MAKE) $(_AuditMakeFlags) $(_AuditOverrides) $(MAKECMDGOALS))
    endif
  $(MAKEFILE_LIST): ;
  .NOTPARALLEL:
else    	#AM_%
  MAKEFILE_LIST :=
  include $(Makefile)
endif   	#AM_%
