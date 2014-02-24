################################################################################
 # Makefile for installing and uninstalling kvm-deploy
 #
 # LICENSE: GNU GENERAL PUBLIC LICENSE Version 3
 #
 # @author      Elwin Andriol
 # @copyright   Copyright (c) 2014 Heuveltop (http://www.heuveltop.nl)
 # @license     http://www.gnu.org/licenses/gpl.html GPLv3
 # @version     $Id:$
 # @link        https://github.com/eandriol/kvm-deploy
 ###############################################################################


################################################################################
 # some directory shortcut variables
 ###############################################################################
PROJ_ROOT	=.
SCRIPTS		=$(PROJ_ROOT)/scripts
BIN_DIR		=/usr/sbin

################################################################################
 # some macro commands
 ###############################################################################
VERSION		=$$( cat $(PROJ_ROOT)/.version )
TIMESTAMP	=$$( date +'%a, %d %b %Y %T %z' )
HOST		=$$( hostname -f )

################################################################################
 # assign command substitution variables.
 # this is a good practice to keep track a better track of binary dependencies
 ###############################################################################
cmd.CHMOD	=chmod
cmd.CHOWN	=chown
cmd.CP		=cp
cmd.ECHO	=echo
cmd.FIND	=find
cmd.LN		=ln
cmd.MKDIR	=mkdir
cmd.RM		=rm
cmd.SED		=sed


################################################################################
 # target declarations, done here to outline following target definition order
 ###############################################################################

.PHONY: all
.PHONY: clean
.PHONY: dummy
.PHONY: install
.PHONY: uninstall
.PHONY: deb-package

################################################################################
 # target definitions
 ###############################################################################

all: dummy
	@#######################################################################
	@ # Doing nothing, this is a target aggregate
	@ ######################################################################


clean:
	@#######################################################################
	@ # Clean target for debuild or pbuilder environment
	@ ######################################################################
	@if [ -d build ]; then rm -rf $(PROJ_ROOT)/build; fi


dummy:
	@#######################################################################
	@ # Dummy target for debuild or pbuilder environment
	@ ######################################################################
	@$(cmd.ECHO) "Just moving along"


install:
	@#######################################################################
	@ # Install binary and config files
	@ ######################################################################
	@$(cmd.CP) $(SCRIPTS)/kvm-deploy.py ${DESTDIR}$(BIN_DIR)/kvm-deploy
	@$(cmd.CHOWN) root:root ${DESTDIR}$(BIN_DIR)/kvm-deploy
	@$(cmd.CHMOD) 0700 ${DESTDIR}$(BIN_DIR)/kvm-deploy
	@$(cmd.MKDIR) ${DESTDIR}/etc/kvm-deploy
	@$(cmd.CP) -r $(PROJ_ROOT)/conf/* ${DESTDIR}/etc/kvm-deploy/
	@$(cmd.CHOWN) -R root:root ${DESTDIR}/etc/kvm-deploy
	@$(cmd.FIND) ${DESTDIR}/etc/kvm-deploy -type d | xargs $(cmd.CHMOD) -R 0700
	@$(cmd.FIND) ${DESTDIR}/etc/kvm-deploy -type f | xargs $(cmd.CHMOD) -R 0600


uninstall:
	@#######################################################################
	@ # Uninstall binary and config files
	@ ######################################################################
	@file=${DESTDIR}$(BIN_DIR)/kvm-deploy; \
	    if [ -e $${file} ]; then $(cmd.RM) -f $${file}; fi
	@dir=${DESTDIR}/etc/kvm-deploy; \
	    if [ -e $${dir} ]; then $(cmd.RM) -rf $${dir}; fi

deb-package: clean
	@#######################################################################
	@ # Generate a deb package
	@ ######################################################################
	@$(cmd.MKDIR) -p $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)
	@$(cmd.CP) -r $(PROJ_ROOT)/conf     $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)
	@$(cmd.CP) -r $(PROJ_ROOT)/debian   $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)
	@$(cmd.CP) -r $(PROJ_ROOT)/scripts  $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)
	@$(cmd.CP) -r $(PROJ_ROOT)/LICENSE  $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)
	@$(cmd.CP) -r $(PROJ_ROOT)/Makefile $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)
	@$(cmd.SED) -i "s|%%HOST%%|$(HOST)|"           $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)/debian/changelog
	@$(cmd.SED) -i "s|%%TIMESTAMP%%|$(TIMESTAMP)|" $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)/debian/changelog
	@$(cmd.SED) -i "s|%%VERSION%%|$(VERSION)|"     $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)/debian/changelog
	@$(cmd.SED) -i "s|%%TIMESTAMP%%|$(TIMESTAMP)|" $(PROJ_ROOT)/build/kvm-deploy-$(VERSION)/debian/copyright
	@cd $(PROJ_ROOT)/build/kvm-deploy-$(VERSION) && debuild -us -uc >/dev/null
	@$(cmd.ECHO) "package location: $$(readlink -f build/*.deb)"
