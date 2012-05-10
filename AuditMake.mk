Makefile ?= Makefile
MAKE := $(notdir $(MAKE))

ifneq (,$(filter AB_%,$(MAKEOVERRIDES)))
  _AuditMakeFlags := --no-print-directory -f $(Makefile)
  _AuditOverrides := $(filter-out AB_%,$(MAKEOVERRIDES))
  ifeq (,$(MAKECMDGOALS))
    .DEFAULT_GOAL = all
  endif
  %:: $(MAKEFILE_LIST)
    ifeq (clean,$(findstring clean,$(MAKECMDGOALS)))
	$(MAKE) $(_AuditMakeFlags) $(MAKECMDGOALS)
    else
	$(strip AuditMake -b $(BaseOfTree) $(if $(AB_DIR),-l $(AB_DIR)) $(AB_FLAGS) -- \
		$(MAKE) $(_AuditMakeFlags) $(_AuditOverrides) $(MAKECMDGOALS))
    endif
  $(MAKEFILE_LIST): ;
  .NOTPARALLEL:
else    	#AB_%
  MAKEFILE_LIST :=
  include $(Makefile)
endif   	#AB_%
