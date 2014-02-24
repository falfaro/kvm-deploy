[KVM-DEPLOY] [1]
======================================================

![Screen Shot](https://raw.github.com/eandriol/kvm-deploy/master/images/screenshot.png)


Introduction
------------
<a name="xref-introduction"></a>

Kvm-deploy is a tool for automated deployment of virtual machines on a
[KVM] [2]/[libvirt] [3] virtualization platform.

Deploying small to mid size KVM platforms can be expensive, not in the least
part because it can involve a lot of manual labor in setting up virtual machines.

Large scale deployments of KVM, for instance with [OpenStack] [4] or
[CloudStack] [5], do have good automated deployment tools. However, these tools
are often not trivial to setup and also create a lot of overhead and complexity
that makes sense for large deployments, but is also hindering cost minimization
on small scale deployments. Many tools also happen to be a lot more vendor/distro
specific then they claim to be, which is not helping matters when trying to
create flexible solutions.

An additional issue can be that most automatic deployment tools are based on
creating virtual machines off of prepared disk images with already installed
operating systems on them. The creation of these images themselves often
involves manual labor and has to be repeated every time a producer distributes a
new version of their operating system in order to stay up to date. This
maintenance need for standard disk images and the fact that creating tailored
prepared images for different deployment needs at best multiplies these costs,
make the small scale deployment of KVM a relatively expensive job.

This is where kvm-deploy can make a difference. It is a lightweight tool
consisting of a [Python] [6] script and a set of [YAML] [7] configuration files.
Kvm-deploy can fully automatically create or replace a virtual machines using a
configuration file. The purpose of kvm-deploy is to get a system up and running
up to the point where a system configuration management tool like [Salt] [8],
[Puppet] [9] or [Chef] [10] can take over.

Kvm-deploy does not rely on prepared disk images, but uses installer images
instead. These are the iso images publicly available from Linux distro producers.
Normally this installation process would require human interaction. However, both
Debian/Ubuntu and Red Hat based/derived Linux distributions also have mechanisms
for automating this process, called [Preseed] [11] and [Kickstart] [12]
respectively.

Kvm-deploy disassembles installer images and injects automation configuration
before it reassembles them again. The result is an installer image specifically
tailored for each individual virtual machine. As a result of this approach,
kvm-deploy is limited to operating systems that have some mechanism for
automating their installation by adding something to their installer iso image.
On the positive side of this limitation, the only action to be taken to upgrade
a virtual machine to a newer version is to change a single configuration entry
and then redeploy the virtual machine.

A key design feature of kvm-deploy is that only a minimal amount of complexity
and knowledge about the structure of configuration files is locked up in the main
script's code. Most configurable aspects of a deployment comes from a freely
editable template file and an accompanying translation table file, which links
variables in a template to values in a deployment's configuration file.

To facilitate the management of larger sets of deployment configuration files,
the standard YAML format has been extended with an include feature. This makes
it possible to put parts of a configuration into a single reusable file. The
result is that a deployment's configuration file can be very compact and only
contain deployment specific information and a set of references to generic
include files. See the [Examples](#xref-examples) for more information.


Installation
------------
<a name="xref-installation"></a>

The simplest way to get started is by cloning the git repository and as root
run:
```bash
make install
```
All this does is install the kvm-deploy script in the /usr/sbin directory and
create a directory with example configurations and templates in the
/etc/kvm-develop directory. Please be aware that this installation happens
outside of the control of your distro's package manager. If kvm-deploy needs to
be uninstalled, this can be done by running:
```bash
make uninstall
```
Be careful because this command also deletes the full /etc/kvm-deploy directory,
including any configuration files you may have made.

Kvm-deploy relies on some other tools, which on a Debian/Ubuntu based system can
be installed with:
```bash
apt-get install rsync libvirt-bin virtinst
```

Once kvm-deploy is installed, the deployment of a virtual machine, its disk
images and associated virtual networks, is as simple as invoking
```bash
kvm-deploy machine
```
Machine has to have a corresponding configuration file called
/etc/kvm-deploy/__machine__.yaml. The name for a configuration file can be
chosen arbitrarily, but a good convention could be to name these files after the
hostname or [FQDN] [13] of they virtual machine the deploy.

For those who are using a Debian/Ubuntu bases system on their
virtualization host machine, a deb package can be created with:

```bash
apt-get install devscripts build-essential fakeroot
make deb-package
```
It may be best to generate the deb package not on the target machine, but e.g.
a temporary virtual machine or on a development system, because the installation
of devscripts and build-essential will also install many other tools that do not
belong on a production machine. The generated deb package can be found in the
projects build directory.


Security
--------
<a name="xref-security"></a>

If any of the [Examples](#xref-examples) is used to create real deployments,
make sure to put newly generated public and private keys in the configuration
file and not reuse the example ones! The same goes for the ssh access
configuration files for [debian] [23] and [ubuntu] [24]. In real deployments it
would be better to have an individual include file for each machine, or define
unique values directly in the machine's deployment file.

Please take not of the fact that because of the flexible nature on the
configuration of kvm-develop, it is also very easy to do bad things by
manipulating configuration and template files.

One way to mitigate some of the security dangers and also to be better equipped
against accidental mishaps, is to keep the whole configuration directory under
the control of a git repository with:
```bash
cd /etc/kvm-deploy
git init
git remote add origin git@your_git_server:your_repository.git
```
Whenever anything is changed to the configuration run:
```bash
cd /etc/kvm-deploy
git add --all
git commit -am "<commit message>"
git push origin master
```
This way the configuration's integrity can always be verified and restored from
a safe location.


Examples
--------
<a name="xref-examples"></a>

Kvm-deploy comes with 3 example deployment configurations to demonstrate some of
kvm-deploy's capabilities. The examples are called [EXAMPLE1] [19], [EXAMPLE2] [20]
and [EXAMPLE3] [21]. They can be deployed with:
```bash
kvm-deploy example1
kvm-deploy example2
kvm-deploy example3
```
A deployment of all the examples will create a situation like this:

![Screen Shot](https://raw.github.com/eandriol/kvm-deploy/master/images/topology.png)

In this illustration, the numbers in orange indicate example values that have to
be adjusted to match the network in which the KVM host is situated. This means
that in order to deploy _EXAMPLE1_, some values need to be edited in the [example's
configuration file] [19], and also in the [network's configuration file] [22].
In order to deploy _EXAMPLE3_, _EXAMPLE1_ needs to already be deployed for it
acts as the gateway router for _EXAMPLE1_. Additionally, for _EXAMPLE3_ to be
deployed, a static route on the KVM host's network gateway router is required.
This static route needs to direct any traffic for the 172.16.1.0/24 network to
the IP address of the primary interface of _EXAMPLE1_. _EXAMPLE2_ does not have
any special requirement and can be deployed without making any changes.

__EXAMPLE1__:
 * Debian 7 VM, with 128 Mbyte of RAM and a single 1 GByte disk image.
 * Directly connected to the KVM host's network for Internet access.
 * Acts as a gateway router for the _virbrXiso1_ virtual network and _EXAMPLE3_.
 * Will create an isolated virtual network (if not existing), called _virbrXiso1_.

__EXAMPLE2__:
 * Debian 7 VM, with 128 Mbyte of RAM and a single 1 GByte disk image.
 * Connected to a NAT forwarding virtual network for Internet access.
 * Will create a NAT forwarding virtual network (if not existing), called _virbrXnat0_.
 * Will create an isolated virtual network (if not existing), called _virbrXiso1_.
 * Will create an isolated virtual network (if not existing), called _virbrXiso2_..

__EXAMPLE3__:
 * Ubuntu 13.10 Server VM, with 256 Mbyte of RAM and a single 2 GByte disk image.
 * Connected to an isolated network (_virbrXiso1_) with a gateway router (_EXAMPLE1_) for Internet access.
 * Will create an isolated virtual network (if not existing), called _virbrXiso1_.
 * Will create an isolated virtual network (if not existing), called _virbrXiso2_..

All examples use USA mirrors as package repositories and UTC for their time zone
settings. It is advised to create include files for your personal location and if
possible use a local APT proxy, which will speed up a deployment considerably.


Improvements
------------
<a name="xref-improvemenst"></a>

- Add support for [RPM package] [14] generation (make rpm-package).
- Add support for [Kickstart] [9], for [Fedora] [15]/[CentOS] [16] deployments.
- Add support for [AutoYaST] [17], for [openSUSE] [18] deployments.


[1]:  https://github.com/eandriol/kvm-deploy            "Project home page"
[2]:  http://www.linux-kvm.org/                         "KVM home page"
[3]:  http://libvirt.org/                               "libvirt home page"
[4]:  http://www.openstack.org/                         "OpenStack home page"
[5]:  http://cloudstack.apache.org/                     "CloudStack home page"
[6]:  http://www.python.org/                            "Python home page"
[7]:  http://www.yaml.org/                              "YAML home page"
[8]:  http://www.saltstack.com/community/               "Salt home page"
[9]:  http://puppetlabs.com/puppet/puppet-open-source   "Puppet home page"
[10]: http://community.opscode.com/                    "Chef home page"
[11]: http://en.wikipedia.org/wiki/Preseed             "Preseed Wikipedia page"
[12]: http://en.wikipedia.org/wiki/Kickstart_(Linux)   "Kickstart Wikipedia page"
[13]: http://en.wikipedia.org/wiki/Fqdn                 "Fully Qualified Domain Name"
[14]: http://en.wikipedia.org/wiki/RPM_Package_Manager  "RPM Wikipedia page"
[15]: http://fedoraproject.org/                         "Fedora home page"
[16]: http://www.centos.org/                            "CentOS home page"
[17]: http://doc.opensuse.org/projects/autoyast/        "AutoYaST documentation page"
[18]: http://www.opensuse.org/en/                       "OpenSUSE home page"
[19]: https://github.com/eandriol/kvm-deploy/blob/master/conf/example1.yaml "/etc/kvm-deploy/example1.yaml"
[20]: https://github.com/eandriol/kvm-deploy/blob/master/conf/example2.yaml "/etc/kvm-deploy/example2.yaml"
[21]: https://github.com/eandriol/kvm-deploy/blob/master/conf/example2.yaml "/etc/kvm-deploy/example3.yaml"
[22]: https://github.com/eandriol/kvm-deploy/blob/master/conf/includes/net/br0example.yaml "/etc/kvm-deploy/includes/net/br0example.yaml"
[23]: https://github.com/eandriol/kvm-deploy/blob/master/conf/includes/distro/debian/ssh/examples.yaml "/etc/kvm-deploy/includes/distro/debian/ssh/examples.yaml"
[24]: https://github.com/eandriol/kvm-deploy/blob/master/conf/includes/distro/ubuntu/ssh/examples.yaml "/etc/kvm-deploy/includes/distro/ubuntu/ssh/examples.yaml"
