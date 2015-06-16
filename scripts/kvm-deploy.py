#!/usr/bin/env python

################################################################################
 # KVM-DEPLOY:
 #
 # ...
 #
 # LICENSE: GNU GENERAL PUBLIC LICENSE Version 3
 #
 # @author      Elwin Andriol
 # @copyright   Copyright (c) 2014 Heuveltop (http://www.heuveltop.nl)
 # @license     http://www.gnu.org/licenses/gpl.html GPLv3
 # @version     $Id:$
 # @link        https://github.com/eandriol/kvm-deploy
 #
 #
 # To understand the inner workings of kvm-deploy, the advice is to read this
 # script in reverse order, i.e. from the bottom to the top. This is because
 # most of the high level code, including the main entry point, is located at
 # the end of the script. Higher up in the script is where more individual 
 # implementation details can be found.
 ###############################################################################


################################################################################
 # Stardard library imports.
 ###############################################################################
import getopt
import grp
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time


################################################################################
 # Individually packaged library imports.
 ###############################################################################
for package in [ 'netaddr', 'yaml' ]:
	try:
		exec "import %s" % package
	
	except:
		print 'missing python-%s library' % package
		sys.exit( 1 )


################################################################################
 # Global constants and variables.
 ###############################################################################
EXITCODE = 0
CONFDIR = '/etc/kvm-deploy'
LIBVIRT_POOL_USER  = 'libvirt-qemu'
LIBVIRT_POOL_GROUP = 'kvm'
LIBVIRT_POOL_BASEDIR = '/var/lib/libvirt/images'
MAX_VM_BOOT_TIME = 60
SCRIPT = os.path.basename( sys.argv[ 0 ] )
USAGE = SCRIPT + ' [--force] machine'
L1INDENT = '   '
L2INDENT = '     '

SSH_CFG = '-i %s -t -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'
SCP_CFG = '-i %s -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'

ISOLINUX_CONFIG = '''
default preseed
prompt 0
timeout 0
label preseed
kernel /%s/vmlinuz
append auto=true priority=high vga=788 initrd=/%s/initrd.gz -- quiet'''

GENISOIMAGE_CMD = '''
genisoimage
-o "%s"
-V "Installer"
-l
-r
-J
-no-emul-boot
-boot-load-size 4
-boot-info-table
-input-charset utf8
-b isolinux/isolinux.bin
-c isolinux/boot.cat
"%s/iso" '''


################################################################################
 # Binary dependencies list.
 ###############################################################################
REQUIRED_BINARIES = [
'cpio',
'find',
'genisoimage',
'gzip',
'md5sum',
'mount',
'ping',
'rsync',
'scp',
'sed',
'sort',
'ssh',
'umount',
'virsh',
'virt-install',
'wget'
]


################################################################################
 # Specialized version of the standard YAML loader class.
 # This loader supports '!include' statements in YAML files.
 ###############################################################################
class KvmDeployConfigLoader( yaml.Loader ):
	def __init__( self, stream ):
		self._root = os.path.split( stream.name )[ 0 ]
		super( KvmDeployConfigLoader, self ).__init__( stream )

	def include( self, node ):
		file = self.construct_scalar( node )
		path = os.path.join( self._root, 'includes', file )

		if not os.path.exists( path ):
			raise KvmDeployException( L1INDENT + "! unable to include %s" % file, 1 )

		print "   - including %s" % file

		with open( path, 'r' ) as f:
			return yaml.load( f, KvmDeployConfigLoader )


################################################################################
 # Specialized exception class for kvm-deploy.
 # This exception is raised whenever an anticipated exception is caught.
 ###############################################################################
class KvmDeployException( Exception ):
	def __init__( self, message, exitcode ):
		self.message = message
		self.exitcode = exitcode

	def getExitCode( self ):
		return self.exitcode

	def getMessage( self ):
		return self.message


################################################################################
 # .
 ###############################################################################
class KvmDeploy:
	def __enter__( self ):
		return self

	def __exit__( self, type, value, traceback ):
		global EXITCODE

		if isinstance( value, KvmDeployException ):
			print value.getMessage()
			
			EXITCODE = value.getExitCode()
			
			if EXITCODE == 2:
				self._cleanup( False )
			
			else:
				self._cleanup()

			return True
		
		self._cleanup()

	def __init__(  self ):
		self.config = None
		self.force = False
		self.tempdir = tempfile.mkdtemp()
		self.installer = '%s/installer.iso' % self.tempdir
		self.sshkey = '%s/rsa_id' % self.tempdir
		self.vm = None
		self.disks = list()
		self.mounted = False
		os.chmod( self.tempdir, 0755 )

	def _checkBinaryDependencies( self ):
		for binary in REQUIRED_BINARIES:
			found = False

			for path in os.environ[ 'PATH' ].split( ':' ):
				if found:
					continue

				if os.path.exists( path + '/' + binary ):
					found = True

			if found:
				continue
			
			raise KvmDeployException( L1INDENT + "! missing required binary: %s" % binary,  2 )

	def _checkNetworkConfiguration( self ):
		config = self.config
		
		for index in range( 0, len( config[ 'vm' ][ 'nic' ] ) ):
			try:
				value = config[ 'vm' ][ 'nic' ][ index ][ 'ip' ]
				netaddr.IPNetwork( value )
			
			except KeyError:
				raise KvmDeployException( L1INDENT + "! vm's nic %d requires ip address" % index,  1 )
			
			except:
				raise KvmDeployException( L1INDENT + "! vm's nic %d: invalid value ip = %s" % ( index, value ),  1 )

			try:
				value = config[ 'vm' ][ 'nic' ][ index ][ 'net' ]
			
			except KeyError:
				raise KvmDeployException( L1INDENT + "! vm's nic %d requires network settings" % index,  1 )

			for key in [ 'netmask', 'network', 'type' ]:
				try:
					value = config[ 'vm' ][ 'nic' ][ index ][ 'net' ][ key ]
					
					if key == 'netmask':
						netaddr.IPNetwork( value )
						
					if key == 'network':
						netaddr.IPNetwork( value )
				
				except KeyError:
					raise KvmDeployException( L1INDENT + "! vm's nic %d requires %s" % ( index, key ),  1 )
				
				except:
					raise KvmDeployException( L1INDENT + "! vm's nic %d: invalid value %s = %s" % ( index, key, value ),  1 )

			if index == 0:
				for key in [ 'gateway', 'dns' ]:
					try:
						value = config[ 'vm' ][ 'nic' ][ index ][ 'net' ][ key ]
						netaddr.IPNetwork( value )
						
					except KeyError:
						raise KvmDeployException( L1INDENT + "! vm's first nic requires %s" % key,  1 )
					
					except:
						raise KvmDeployException( L1INDENT + "! vm's nic %d: invalid value %s = %s" % ( index, key, value ),  1 )

	def _checkUser( self ):
		if os.geteuid() != 0:
			raise KvmDeployException( L1INDENT + "! need to have root privileges to run this script",  1 )
		
	def _checkVmConfiguration( self ):
		distro = self.config[ 'distro' ][ 'type' ]

		if distro == 'debian':
			if self.vm[ 'mem' ] < 128:
				raise KvmDeployException( L1INDENT + "! debian requires at least 256 MByte memory",  1 )
			
		if distro == 'ubuntu':
			if self.vm[ 'mem' ] < 256:
				raise KvmDeployException( L1INDENT + "! ubuntu requires at least 256 MByte memory",  1 )
				
	def _cleanup( self, feedback = True ):
		if feedback == True:
			print " * Deleting temporary files"

		if self.mounted:
			command = 'killall rsync'
			self._execute( command, None )
			time.sleep( 1 )
			command = 'umount -f %s/mnt' % self.tempdir
			self._execute( command, None )

		shutil.rmtree( self.tempdir )

	def _createDebianInstaller( self ):
		print "   - creating checksums"
		command = 'cd "%s/iso" && md5sum `find -type f` | sed "/md5sum/d" | sort -k 2 > md5sum.txt' % self.tempdir
		self._execute( command, L2INDENT + '! failed' )
		print "   - generating installer"
		command = GENISOIMAGE_CMD % ( self.installer, self.tempdir )
		p = re.compile( '\s*\n\s*', flags=re.MULTILINE )
		command = re.sub( p, ' ', command ).strip()
		self._execute( command, L2INDENT + '! failed' )
		os.chmod( self.installer, 0644 )

	def _createDebianInstallerInitrd( self, initrd ):
		print "   - compressing initrd"
		command = 'cd "%s/initrd" && find . -print0 | cpio -0 -H newc -ov 2>/dev/null | gzip -9c > "%s"' % ( self.tempdir, initrd )
		self._execute( command, L2INDENT + '! failed' )

	def _createDebianInstallerIsolinuxConfig( self, initrd ):
		print "   - configuring isolinux"

		try:
			f = open( '%s/iso/isolinux/isolinux.cfg' % self.tempdir, 'w' )
		
		except IOError:
			raise KvmDeployException( L2INDENT + "! failed",  1 )
		else:
			p = os.path.basename( os.path.dirname( initrd ) )
			data = ISOLINUX_CONFIG  % ( p, p )
			p = re.compile( '\s*\n\s*', flags=re.MULTILINE )
			data = re.sub( p, '\n', data ).strip()
			f.write( data )
			f.close()

	def _createDiskImage( self, disk, index ):
		print "   - installing disk %d" % index
		print "     name: %s" % disk[ 'name' ]
		print "     pool: %s" % disk[ 'pool' ]
		print "     type: %s" % disk[ 'format' ]
		print "     size: %s" % disk[ 'size' ]
		self._execute( disk[ 'cmd' ], L2INDENT + '! failed' )

	def _createDiskPool( self, pool ):
		print "   - creating disk pool %s" % pool
		path = '%s/%s' % ( LIBVIRT_POOL_BASEDIR, pool )

		if not os.path.exists( path ):
			os.makedirs( path )

		uid = pwd.getpwnam( LIBVIRT_POOL_USER ).pw_uid
		gid = grp.getgrnam( LIBVIRT_POOL_GROUP ).gr_gid
		os.chown( path, uid, gid )
		file = "%s/%s.xml" % ( self.tempdir, pool )
		template = '%s/templates/virsh/pool.template' % CONFDIR
		table    = '%s/templates/virsh/pool.table'    % CONFDIR
		params   = [ ( 'name', '"%s"' % pool ), ( 'path', '"%s"' % path ) ]
		data = self._processTemplate( template, table, params )

		with open( file, 'w' ) as f:
			f.write( data )
			f.close()

		command = 'virsh pool-define %s' % file
		self._execute( command, L2INDENT + '! failed to define pool' )
		command = 'virsh pool-autostart %s' % pool
		self._execute( command, L2INDENT + '! failed to autostart pool' )
		command = 'virsh pool-start %s' % pool
		self._execute( command, L2INDENT + '! failed to start pool' )

	def _createInitrdPreseed( self ):
		print "   - creating preseed"
		type = self.config[ 'distro' ][ 'type' ]

		try:
			f = open( '%s/initrd/preseed.cfg' % self.tempdir, 'w' )
		
		except IOError:
			raise KvmDeployException( L2INDENT + "! failed",  1 )
		
		else:
			f.write( self.config[ 'distro' ][ type ][ 'preseed' ] )
			f.close()

	def _createNetwork( self, net, index ):
		template = '%s/templates/virsh/network/%s.template' % ( CONFDIR, net[ 'template' ] )
		table    = '%s/templates/virsh/network/%s.table'    % ( CONFDIR, net[ 'template' ] )

		for file in [ template, table ]:
			if not os.path.exists( file ):
				raise KvmDeployException( L1INDENT + "! invalid network template: %s" % net[ 'template' ],  1 )

		xml = self._processTemplate( template, table, [ ( 'net.', 'config.vm.nic[%d].net.' % index ) ] )
		file = '%s/network.xml' % self.tempdir

		with open( file, 'w' ) as f:
			f.write( xml )
			f.close()

		print "   - creating network %s" % net[ 'name' ]
		command = 'virsh net-define %s' % file
		self._execute( command, L2INDENT + '! failed to define net' )
		command = 'virsh net-autostart %s' % net[ 'name' ]
		self._execute( command, L2INDENT + '! failed to autostart net' )
		command = 'virsh net-start %s' % net[ 'name' ]
		self._execute( command, L2INDENT + '! failed to start net' )

	def _createSshPrivateKey( self ):
		type = self.config[ 'distro' ][ 'type' ]
		ssh = self.config[ 'distro' ][ type ][ 'ssh' ]
		key = ssh[ 'access' ][ 'rsa' ][ 'pri' ].strip()
		
		try:
			f = open( self.sshkey, 'w' )
		
		except IOError:
			raise KvmDeployException( L2INDENT + "! failed writing ssh udentity file",  1 )
		
		else:
			f.write( key )
			f.close()

		os.chmod( self.sshkey, 0600 )

	def _createVirtualMachine( self ):
		print "   - installing vm"
		print "     name:  %s" % self.vm[ 'name' ]
		print "     ip:    %s" % self.vm[ 'ip' ]
		print "     mem:   %s Mbyte" % self.vm[ 'mem' ]
		print "     cpu's: %s" % self.vm[ 'cpus' ]
		self._execute( self.vm[ 'cmd' ], L2INDENT + '! failed' )

	def _destroyExistingDiskImages( self ):
		for index in range( 0, len( self.disks ) ):
			disk = self.disks[ index ]

			if not self._isExistingDiskPool( disk[ 'pool' ] ):
				continue

			if self._isExistingDiskImage( disk[ 'pool' ], disk[ 'name' ] ):
				if self.force:
					print "   - removing existing disk image %d" % index
					command = 'virsh vol-delete --pool %s %s ' % ( disk[ 'pool' ], disk[ 'name' ] )
					self._execute( command, L2INDENT + '! failed removing old image file' )
				
				else:
					raise KvmDeployException( L1INDENT + "! image file already exists, require --force option",  1 )

	def _destroyExistingVirtualMachine( self ):
		command = 'virsh dominfo %s | grep ^State' % self.vm[ 'name' ]
		p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
		p.wait()
		state = p.stdout.read( 1024 )

		if state:
			if self.force:
				if 'running' in state:
					print "   - stopping existing virtual machine"
					command = 'virsh destroy %s ' % self.vm[ 'name' ]
					self._execute( command, L2INDENT + '! failed shutting down existing virtual machine' )

				print "   - removing existing virtual machine"
				command = 'virsh undefine %s ' % self.vm[ 'name' ]
				self._execute( command, L2INDENT + '! failed removing existing virtual machine' )
			
			else:
				raise KvmDeployException( L1INDENT + "! virtual machine already exists, require --force option",  1 )

	def _execute( self, command, error ):
		p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.STDOUT )

		if p.wait() != 0:
			print "command: '%s' failed with output:" % command
			print p.stdout.read( 1024 * 1024 )

			if error != None:
				raise KvmDeployException( error,  1 )

	def _extractInitrd( self, initrd ):
		print "   - extracting initrd"
		command = 'cd "%s/initrd" && gzip -d < "%s" | cpio --extract --make-directories --no-absolute-filenames' % ( self.tempdir, initrd )
		self._execute( command, L2INDENT + '! failed' )

	def _extractInstallerContents( self, source ):
		print "   - mounting image"
		dir = self.tempdir
		command = 'mount -o loop %s %s/mnt' % ( source, dir )
		self._execute( command, L2INDENT + '! failed' )
		self.mounted = True
		print "   - copying files"
		command = 'rsync -a -H --exclude=TRANS.TBL "%s/mnt/" "%s/iso/" ' % ( dir ,dir )
		
		try:
			p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
		
		except:
			raise KvmDeployException( L2INDENT + "! failed",  1 )
		
		if p.wait() != 0:
			raise KvmDeployException( L2INDENT + "! failed",  1 )

		print "   - unmounting image"
		command = 'umount -f %s/mnt' % ( dir )
		self._execute( command, L2INDENT + '! failed' )
		self.mounted = False
		
	def _getDebianInstallerInitrd( self ):
		dir = self.tempdir
		
		if os.path.exists( "%s/iso/install.386/initrd.gz" % dir ):
			return "%s/iso/install.386/initrd.gz" % dir
		
		elif os.path.exists( "%s/iso/install.amd/initrd.gz" % dir ):
			return "%s/iso/install.amd/initrd.gz" % dir
		
		raise KvmDeployException( L1INDENT + "! unsupported iso image format", 1 )

	def _getUbuntuInstallerInitrd( self ):
		dir = self.tempdir
		
		if os.path.exists( "%s/iso/install/initrd.gz" % dir ):
			return "%s/iso/install/initrd.gz" % dir
		
		raise KvmDeployException( L1INDENT + "! unsupported iso image format", 1 )
		
	def _getInstallerSource( self ):
		iso = self.config[ 'distro' ][ 'iso' ]
		source = '%s/%s' % ( iso[ 'path' ], iso[ 'file' ] )

		if not os.path.exists( source ):
			print "   - downloading installer image"

			if not os.path.exists( iso[ 'path' ] ):
				os.makedirs( iso[ 'path' ] )

			command = 'wget -O %s "%s" ' % ( source, iso[ 'source' ] )

			with open( os.devnull, 'w' ) as sink:
				p = subprocess.Popen( command, shell = True, stdout = sink, stderr = sink )
				
				if p.wait() != 0:
					raise KvmDeployException( L2INDENT + "! failed",  1 )
			
		return source

	def _getNetworkState( self, name ):
		command = 'virsh net-list --all | tail -n +3 | grep "^%s\\s"' % name
		p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
		p.wait()
		feedback = p.stdout.read( 1024 )

		if 'inactive' in feedback:
			return 'inactive'
		
		if 'active' in feedback:
			return 'active'

		return None

	def _isExistingDiskImage( self, pool, name ):
		command = 'virsh vol-list %s | grep "^%s\\s" ' % ( pool, name )
		p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
		p.wait()

		if p.stdout.read( 1024 ):
			return True
		
		return False

	def _isExistingDiskPool( self, pool ):
		command = 'virsh pool-list --all| grep "^%s\\s" ' % pool
		p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
		p.wait()

		if p.stdout.read( 1024 ):
			return True

		return False

	def _onDebianVmConfigureExtraNetworkInterfaces( self ):
		ip = self.vm[ 'ip' ]
		config = self.config
		options = SSH_CFG % self.sshkey
		file = '%s/nic' % self.tempdir
		action  = "cat >> /etc/network/interfaces"
		command = 'cat %s | ssh %s root@%s "%s" ' % ( file, options, ip, action )
		
		if len( config[ 'vm' ][ 'nic' ] ) > 1:
			for index in range( 1, len( config[ 'vm' ][ 'nic' ] ) ):
				address = config[ 'vm' ][ 'nic' ][ index ][ 'ip' ]
				netmask = config[ 'vm' ][ 'nic' ][ index ][ 'net' ][ 'netmask' ]
				network = config[ 'vm' ][ 'nic' ][ index ][ 'net' ][ 'network' ]
				data  = "\n"
				data += "allow-hotplug eth%d\n" % index
				data += "iface eth%d inet static\n" % index
				data += "\taddress %s\n" % address
				data += "\tnetmask %s\n" % netmask
				data += "\tnetwork %s\n" % network
				data += "\tbroadcast %s\n" % str( netaddr.IPNetwork( '%s/%s' % ( network, netmask ) ).broadcast )

				with open( file, 'w' ) as f:
					f.write( data )
					f.close()

				print "   - configuring nic eth%d" % index
				self._execute( command, L2INDENT + '! failed' )

	def _onDebianVmConfigureRouting( self ):
		ip = self.vm[ 'ip' ]
		config = self.config
		type = config[ 'distro' ][ 'type' ]
		options = SSH_CFG % self.sshkey
		
		for tech in [ 'ipv4', 'ipv6' ]:
			try:
				if config[ 'distro' ][ type ][ 'route' ][ tech ]:
					print "   - enabling %s forwarding" % tech

					if tech == 'ipv4':
						action  = "sed -i 's|#\\?net\\.ipv4\\.ip_forward=.*$|net.ipv4.ip_forward=1|' /etc/sysctl.conf"
					
					else:
						action  = "sed -i 's|#\\?net\\.ipv6\\.conf\\.all\\.forwarding=.*$|net.ipv6.conf.all.forwarding=1|' /etc/sysctl.conf"
				else:
					print "   - disabling %s forwarding" % tech

					if tech == 'ipv4':
						action  = "sed -i 's|#\\?net\\.ipv4\\.ip_forward=.*$|#net.ipv4.ip_forward=1|' /etc/sysctl.conf"
					
					else:
						action  = "sed -i 's|#\\?net\\.ipv6\\.conf\\.all\\.forwarding=.*$|#net.ipv6.conf.all.forwarding=1|' /etc/sysctl.conf"

				command = 'ssh %s root@%s "%s" ' % ( options, ip, action )
				self._execute( command, L2INDENT + '! failed updating settings' )
			except KeyError:
				raise KvmDeployException( L1INDENT + "! invalid routing setting",  1 )

	def _onDebianVmDisableBootLoaderDelay( self ):
		print "   - disabling boot loader delay"
		ip = self.vm[ 'ip' ]
		action  = "sed -i 's|^GRUB_TIMEOUT=.*$|GRUB_TIMEOUT=0|' /etc/default/grub; update-grub"
		options = SSH_CFG % self.sshkey
		command = 'ssh %s root@%s "%s" ' % ( options, ip, action )
		self._execute( command, L2INDENT + '! failed' )

	def _onDebianVmInstallSshServerIndentities( self ):
		ip = self.vm[ 'ip' ]
		config = self.config
		type = config[ 'distro' ][ 'type' ]
		ssh = config[ 'distro' ][ type ][ 'ssh' ]
		file = '%s/key' % self.tempdir
		options = SCP_CFG % self.sshkey

		for type in [ 'dsa', 'ecdsa', 'ed25519', 'rsa' ]:
			for side in [ 'pub', 'pri' ]:
				try:
					key = ssh[ 'server' ][ type ][ side ]

					with open( file, 'w' ) as f:
						f.write( key )
						f.close()

					if side == 'pub':
						print "   - installing ssh server identity (%s)" % type
						os.chmod( file, 0644 )
						dst = '/etc/ssh/ssh_host_%s_key.pub' % type

					if side == 'pri':
						os.chmod( file, 0600 )
						dst = '/etc/ssh/ssh_host_%s_key' % type
					
					command = 'scp %s %s root@%s:%s' % ( options, file, ip, dst )
					self._execute( command, L2INDENT + '! failed' )
				
				except KeyError:
					pass

	def _onUbuntuVmConfigureExtraNetworkInterfaces( self ):
		ip = self.vm[ 'ip' ]
		config = self.config
		options = SSH_CFG % self.sshkey
		file = '%s/nic' % self.tempdir
		action  = "cat >> /etc/network/interfaces"
		command = 'cat %s | ssh %s root@%s "%s" ' % ( file, options, ip, action )
		
		if len( config[ 'vm' ][ 'nic' ] ) > 1:
			for index in range( 1, len( config[ 'vm' ][ 'nic' ] ) ):
				address = config[ 'vm' ][ 'nic' ][ index ][ 'ip' ]
				netmask = config[ 'vm' ][ 'nic' ][ index ][ 'net' ][ 'netmask' ]
				network = config[ 'vm' ][ 'nic' ][ index ][ 'net' ][ 'network' ]
				data  = "\n"
				data += "auto eth%d\n" % index
				data += "iface eth%d inet static\n" % index
				data += "\taddress %s\n" % address
				data += "\tnetmask %s\n" % netmask
				data += "\tnetwork %s\n" % network
				data += "\tbroadcast %s\n" % str( netaddr.IPNetwork( '%s/%s' % ( network, netmask ) ).broadcast )

				with open( file, 'w' ) as f:
					f.write( data )
					f.close()

				print "   - configuring nic eth%d" % index
				self._execute( command, L2INDENT + '! failed' )

	def _onUbuntuVmConfigureRouting( self ):
		self._onDebianVmConfigureRouting()

	def _onUbuntuVmDisableBootLoaderDelay( self ):
		self._onDebianVmDisableBootLoaderDelay()

	def _onUbuntuVmInstallSshServerIndentities( self ):
		self._onDebianVmInstallSshServerIndentities()

	def _onVmInstallSalt( self ):
		ip = self.vm[ 'ip' ]
		ssh_options = SSH_CFG % self.sshkey
		scp_options = SCP_CFG % self.sshkey

		try:
			distro = self.config[ 'distro' ][ 'type' ]
			salt = self.config[ 'distro' ][ distro ][ 'salt' ]

			if salt[ 'role' ] == 'master':
				print "   - installing salt master"
				src = '%s/salt/conf/%s' % ( CONFDIR, salt[ 'config' ] )
				dst = '/etc/salt'
				action  = 'mkdir -p %s' %dst
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed creating state dir' )
				command = 'scp %s -r %s/* root@%s:%s/' % ( scp_options, src, ip, dst )
				self._execute( command, L2INDENT + '! failed copying config files' )
				src = '%s/salt/state/%s' % ( CONFDIR, salt[ 'state' ] )
				dst = '/srv/salt'
				action  = 'mkdir -p %s' %dst
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed creating state dir' )
				command = 'scp %s -r %s/* root@%s:%s/' % ( scp_options, src, ip, dst )
				self._execute( command, L2INDENT + '! failed copying state files' )
				action  = 'wget --no-check-certificate -O installer http://bootstrap.saltstack.org'
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed downloading installer' )
				action  = 'sh installer -M stable'
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed executing installer' )
				action  = 'rm installer'
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed removing installer' )

			if salt[ 'role' ] == 'minion':
				print "   - installing salt minion"
				src = '%s/salt/conf/%s' % ( CONFDIR, salt[ 'config' ] )
				dst = '/etc/salt'
				action  = 'mkdir -p %s/*' %dst
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed clean config dir' )
				command = 'scp %s -r %s/* root@%s:%s/' % ( scp_options, src, ip, dst )
				self._execute( command, L2INDENT + '! failed copying config files' )
				action  = 'wget --no-check-certificate -O installer http://bootstrap.saltstack.org'
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed downloading installer' )
				action  = 'sh installer stable'
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed executing installer' )
				action  = 'rm installer'
				command = 'ssh %s root@%s "%s" ' % ( ssh_options, ip, action )
				self._execute( command, L2INDENT + '! failed removing installer' )

		except KeyError:
			pass

	def _parseReplaceTable( self, file, config, params = None ):
		with open( file ) as f:
			table = f.readlines()

		for i in range( 0, len( table ) ):
			( key, value ) = re.split( '\s+', table[ i ].strip(), 1 )

			if isinstance( params, list ):
				for ( k, v ) in params:
					value = value.replace( k, v )

			if len( re.findall( '(config(\.[a-zA-Z0-9\[\]]+)+)', value ) ):
				for search in re.findall( '(config(\.[a-zA-Z0-9\[\]]+)+)', value ):
					search = search[ 0 ]
					replace = 'config'

					for item in search.split( '.' )[ 1 : ]:
						if '[' in item:
							replace += '[\'' + item.replace( '[', '\'][', 1 )
						
						else:
							replace += '[\'' + item + '\']'

					value = value.replace( search, replace )

			try:
				exec 'value= str(' + value + ')'
			
			except:
				raise KvmDeployException( L1INDENT + "! invalid config: %s" % value,  1 )

			table[ i ] = ( key, value )

		return table

	def _preparePreseedInstaller( self ):
		os.mkdir( self.tempdir + '/iso' )
		os.mkdir( self.tempdir + '/mnt' )
		os.mkdir( self.tempdir + '/initrd' )

	def _processCommandLineParameters( self, argv ):
		try:
			opts, args = getopt.getopt( argv[1:], 'h', [ 'force' ] )
		except getopt.GetoptError:
			raise KvmDeployException( USAGE,  2 )

		for opt, arg in opts:
			if opt == '-h':
				raise KvmDeployException( USAGE,  2 )

			if opt == '--force':
				self.force = True

		if len( args ) != 1:
			raise KvmDeployException( USAGE,  2 )
		
		return args[ 0 ]

	def _processDistroConfig( self ):
		try:
			distro = self.config[ 'distro' ][ 'type' ]
			
			if distro == 'debian' or distro == 'ubuntu':
				self._processPreseedTemplate( distro )

			else:
				raise KvmDeployException( L1INDENT + "! invalid config: unsupported distro type",  1 )
		
		except KeyError:
			raise KvmDeployException( L1INDENT + "! invalid config: missing distro type",  1 )

	def _processPreseedTemplate( self, distro ):
		config = self.config
		
		try:
			template = '%s/templates/distro/%s/preseed/%s.template' % ( CONFDIR, distro, config[ 'distro' ][ distro ][ 'preseed' ] )
			table    = '%s/templates/distro/%s/preseed/%s.table'    % ( CONFDIR, distro, config[ 'distro' ][ distro ][ 'preseed' ] )
		
		except KeyError:
			raise KvmDeployException( L1INDENT + "! invalid config: missing preseed template or table",  1 )

		self.config[ 'distro' ][ distro ][ 'preseed' ] = self._processTemplate( template, table )

	def _processTemplate( self, template, table, params = None ):
		config = self.config

		for file in [ template, table  ]:
			if not os.path.exists( file ):
				raise KvmDeployException( L1INDENT + "! config file %s does not exist" % file,  1 )

		table = self._parseReplaceTable( table, config, params )

		with open( template ) as f:
			template = f.read( 1024 * 1024 ).strip()

		p = re.compile( '\s*\\\\\n\s*', flags=re.MULTILINE )
		template = re.sub( p, ' ', template )

		for key, value in table:
			template = template.replace( key, value )

		return template

	def _processVmConfig( self ):
		config = self.config
		template = '%s/templates/virsh/vm.template' % CONFDIR
		table    = '%s/templates/virsh/vm.table'    % CONFDIR
		self.vm = dict()

		for key, value in self._parseReplaceTable( table, config ):
			for id in [ 'cpus', 'mem', 'name' ]:
				if key == '%%' + id.upper() + '%%':
					self.vm[ id ] = value

		self.vm[ 'ip' ] = config[ 'vm' ][ 'nic' ][ 0 ][ 'ip' ]
		self.vm[ 'cmd' ] = self._processTemplate( template, table )

		if isinstance( config[ 'vm' ][ 'disk' ], list ):
			for index in range( 0, len( config[ 'vm' ][ 'disk' ] ) ):
				template = '%s/templates/virsh/disk.template' % CONFDIR
				table    = '%s/templates/virsh/disk.table'    % CONFDIR
				disk = dict()

				for key, value in self._parseReplaceTable( table, config, [ ( 'INDEX', str( index ) ) ] ):
					for id in [ 'format', 'name', 'pool', 'size' ]:
						if key == '%%' + id.upper() + '%%':
							disk[ id ] = value

				disk[ 'cmd' ] = self._processTemplate( template, table, [ ( 'INDEX', str( index ) ) ] )
				self.disks.append( disk )

				template = '%s/templates/virsh/vm/disk.template' % CONFDIR
				table    = '%s/templates/virsh/vm/disk.table'    % CONFDIR
				self.vm[ 'cmd' ] += ' ' + self._processTemplate( template, table, [ ( 'INDEX', str( index ) ) ] )

		if isinstance( config[ 'vm' ][ 'nic' ], list ):
			for index in range( 0, len( config[ 'vm' ][ 'nic' ] ) ):
				template = '%s/templates/virsh/vm/nic.template' % CONFDIR
				table    = '%s/templates/virsh/vm/nic.table'    % CONFDIR
				self.vm[ 'cmd' ] += ' ' + self._processTemplate( template, table, [ ( 'INDEX', str( index ) ) ] )

	def _readConfigFile( self, file ):
		if not os.path.exists( file ):
			raise KvmDeployException( L1INDENT + "! config file %s does not exist" % file,  1 )

		print "   - using %s" % file
		KvmDeployConfigLoader.add_constructor( '!include', KvmDeployConfigLoader.include )
		
		with open( file ) as f:
			self.config = yaml.load( f, KvmDeployConfigLoader )

	def _rebootVirtualMachine( self ):
		print "   - restarting"
		ip = self.vm[ 'ip' ]
		action  = 'reboot'
		options = SSH_CFG % self.sshkey
		command = 'ssh %s root@%s "%s" ' % ( options, ip, action )
		self._execute( command, L2INDENT + '! failed' )

	def _restartVirtualMachine( self ):
		print "   - restarting"
		command = 'virsh start %s' % self.vm[ 'name' ]
		self._execute( command, L2INDENT + '! failed' )
		deadline = int( time.time() ) + MAX_VM_BOOT_TIME
		command = 'ping -c 1 -W 1 %s' % self.vm[ 'ip' ]
		p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
		p.wait()

		while '100% packet loss' in p.stdout.read( 1024 ):
			time.sleep( 5 )
			p = subprocess.Popen( command, shell = True, stdout = subprocess.PIPE, stderr = subprocess.PIPE )
			p.wait()
			
			if int( time.time() ) > deadline:
				raise KvmDeployException( L2INDENT + "! timed out",  1 )

	def _startNetwork( self, name ):
		print "   - starting inactive network %s" % name
		command = 'virsh net-start %s' % name
		self._execute( command, L2INDENT + '! failed' )


	############################################################################
	 # .
	 ###########################################################################
	def buildDisks( self ):
		print " * Building disk images"

		for index in range( 0, len( self.disks ) ):
			disk = self.disks[ index ]
			
			if not self._isExistingDiskPool( disk[ 'pool' ] ):
				self._createDiskPool( disk[ 'pool' ] )
			
			self._createDiskImage( disk, index )


	############################################################################
	 # .
	 ###########################################################################
	def buildInstaller( self ):
		print " * Building installer"
		distro = self.config[ 'distro' ][ 'type' ]
		source = self._getInstallerSource()

		if distro == 'debian' or distro == 'ubuntu':
			self._preparePreseedInstaller()
			self._extractInstallerContents( source )
			
			if distro == 'debian':
				initrd = self._getDebianInstallerInitrd()
				
			if distro == 'ubuntu':
				initrd = self._getUbuntuInstallerInitrd()
				
			self._extractInitrd( initrd )
			self._createInitrdPreseed()
			self._createDebianInstallerInitrd( initrd )
			self._createDebianInstallerIsolinuxConfig( initrd )
			self._createDebianInstaller()


	############################################################################
	 # .
	 ###########################################################################
	def buildNetworks( self ):
		print " * Building networks"
		interfaces = self.config[ 'vm' ][ 'nic' ]

		for index in range( 0, len( interfaces ) ):
			net = interfaces[ index ][ 'net' ]

			if net[ 'type' ] == 'network':
				state = self._getNetworkState( net[ 'name' ] )
				
				if state == None:
					self._createNetwork( net, index )
				
				elif state == 'inactive':
					self._startNetwork( net[ 'name' ] )


	############################################################################
	 # .
	 ###########################################################################
	def buildVirtualMachine( self ):
		print " * Building virtual machine"
		distro = self.config[ 'distro' ][ 'type' ]
		self._createVirtualMachine()
		self._restartVirtualMachine()

		if distro == 'debian':
			self._createSshPrivateKey()
			self._onDebianVmDisableBootLoaderDelay()
			self._onDebianVmInstallSshServerIndentities()
			self._onDebianVmConfigureExtraNetworkInterfaces()
			self._onDebianVmConfigureRouting()
		
		if distro == 'ubuntu':
			self._createSshPrivateKey()
			self._onUbuntuVmDisableBootLoaderDelay()
			self._onUbuntuVmInstallSshServerIndentities()
			self._onUbuntuVmConfigureExtraNetworkInterfaces()
			self._onUbuntuVmConfigureRouting()

		self._onVmInstallSalt()
		self._rebootVirtualMachine()


	############################################################################
	 # .
	 ###########################################################################
	def checkRequirements( self ):
		print " * Checking requirements"
		self._checkUser()
		self._checkBinaryDependencies()
		self._checkVmConfiguration()
		self._checkNetworkConfiguration()
		self._destroyExistingVirtualMachine()
		self._destroyExistingDiskImages()


	############################################################################
	 # .
	 ###########################################################################
	def processConfig( self, argv ):
		vm = self._processCommandLineParameters( argv )
		print " * Processing configuration"
		self._readConfigFile( '%s/%s.yaml' % ( CONFDIR, vm ) )
		self._processVmConfig()
		self._processDistroConfig()


	############################################################################
	 # .
	 ###########################################################################
	def run( self, argv ):
		self.processConfig( argv )
		self.checkRequirements()
		self.buildInstaller()
		self.buildDisks()
		self.buildNetworks()
		self.buildVirtualMachine()


################################################################################
 # Kvm-deploy's main entry point.
 ###############################################################################
if __name__ == "__main__":
	with KvmDeploy() as application:
		application.run( sys.argv )

	sys.exit( EXITCODE )
