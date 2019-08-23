#!/usr/bin/env python
#import os
#import sys
import time
from time import sleep

# Fix setuptools' evil madness, and open up (more?) security holes
#if 'PYTHONPATH' in os.environ:
#    sys.path = os.environ[ 'PYTHONPATH' ].split( ':' ) + sys.path

from distrinet.topodc import (HadoopDumbbellTopo, getHadoopMaster, DumbbellTopo)

from distrinet.cloud.cloudcontroller import (LxcRemoteController)

from distrinet.cloud.lxc_container import (LxcNode)
from distrinet.cloud.cloudswitch import (LxcOVSSwitch)
from distrinet.cloud.cloudlink import (CloudLink)
from distrinet.distrinet import (Distrinet)

from util import makeFile, makeHosts

from optparse import OptionParser
"""
Example:
    python3 iperf_test.py --pub-id="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDgEnskmrOMpOht9KZV2rIYYLKkw4BSd8jw4t9cJKclE9BEFyPFr4H4O0KR85BP64dXQgAYumHv9ufnNe1jntLhilFql2uXmLcaJv5nDFdn7YEd01GUN2QUkNy6yguTO8QGmqnpKYxYiKz3b8mWDWY2vXaPvtHksaGJu2BFranA3dEuCFsVEP4U295z6LfG3K0vr+M0xawhJ8GRUnX+EyjK5rCOn0Nc04CmSVjIpNazyXyni4cW4q8FUADtxoi99w9fVIlFcdMAgoS65FxAxOF11bM6EzbJczdN4d9IjS4NPBqcWjwCH14ZWUAXvv3t090tUQOLGdDOih+hhPjHTAZt root@7349f78b2047" -n 10  --jump "52.47.186.84" --master="ip-10-0-0-39" --cluster="ip-10-0-0-39,ip-10-0-1-247"
"""
if __name__ == "__main__":
    import time
    start = time.time()

    host, switch, link = LxcNode, LxcOVSSwitch, CloudLink

    parser = OptionParser()
    parser.add_option("--pub-id", dest="pub_id",
                      help="public key to access the cloud", metavar="pub_id")
    parser.add_option("-n", dest="n", default=4,
                      help="number of hosts to emulate", metavar="n")
    parser.add_option("-s", "--single", dest="single", default=False,
                      action="store_true", help="Should we run the experiment on one machine only", metavar="single")
    parser.add_option("-j","--jump", dest="jump",
                      help="jump node (bastion)", metavar="jump")
    parser.add_option("-m","--master", dest="master",
                      help="master node name", metavar="master")
    parser.add_option("-c","--cluster", dest="cluster",
                      help="clusters nodes (their LXC name)", metavar="cluster")
    (options, args) = parser.parse_args()

    # The public key to use
    pub_id = options.pub_id

    # number of hosts in the dumbbell
    n = int(options.n)

    topo = HadoopDumbbellTopo(n=n, pub_id=pub_id, sopts={"image":"switch","controller":"c0", 'pub_id':pub_id, "cpu":8, "memory":"2GB"}, hopts={"image":"ubuntu", 'pub_id':pub_id, "cpu":4, "memory":"8GB"}, lopts={"rate":1000})


    # should we deploy to Amazon first?
    #    nope
    if options.jump:
        print ("# Already deployed")
        assert options.master, "must provide a master when a jump is provided"
        assert options.cluster, "must provide a cluster when a jump is provided"
        jump = options.jump
        master= options.master
        cluster = options.cluster.split(",")
    #    yep
    else:
        print ("# Deploy on Amazon")
        from distrinet.cloud.awsprovision import distrinetAWS

        vpcname = "demo_{}".format(int(time.time()))
        o = distrinetAWS(VPCName=vpcname, addressPoolVPC="10.0.0.0/16", publicSubnetNetwork='10.0.0.0/24',
                         privateSubnetNetwork='10.0.1.0/24',
                         bastionHostDescription={"numberOfInstances": 1, 'instanceType': 't3.2xlarge', 'KeyName': 'pub_dsaucez',
                                                 'ImageId': 'ami-03bca18cb3dc173c9',
                                                 "BlockDeviceMappings":[{"DeviceName": "/dev/sda1","Ebs" : { "VolumeSize" : 50 }}]},
                         workersHostsDescription=[{"numberOfInstances": 4, 'instanceType': 't3.2xlarge',
                                                   'ImageId': 'ami-03bca18cb3dc173c9',
                                                   "BlockDeviceMappings":[{"DeviceName": "/dev/sda1","Ebs" : { "VolumeSize" : 50 }}]}
                                                  ])
        print(o.ec2Client)
        jump, master, workerHostsPrivateIp = o.deploy()
        cluster = [master] + workerHostsPrivateIp

        print ("# sleep 60s to wait for LXD to do its magic")
        sleep(60)
    print ("jump:", jump, "mastername:", master, "clustername:", cluster)

    adminIpBase='192.168.0.1/8'
    ipBase='10.0.0.0/8'
    inNamespace=False
    xterms=False
    autoSetMacs=True
    waitConnected=False
    autoSetMacs=False
    autoStaticArp=False
    autoPinCpus=False
    listenPort=6654
    user="root"
    client_keys=["/root/.ssh/id_rsa"]
    build=False

    def _singleMachine(topo, cluster):
        places = {}
        hosts = topo.hosts()
        for i in range(len(hosts)):
            places[hosts[i]] = cluster[0]
        places["s1"] = cluster[0]
        places["s2"] = cluster[0]
        return places

    def _twoMachines(topo, cluster):
        places = {}
        hosts = topo.hosts()
        for i in range(len(hosts)):
            target = cluster[0]
            if i >= int(len(hosts)/2):
                target = cluster[1]
            places[hosts[i]] = target
        places["s1"] = cluster[0]
        places["s2"] = cluster[1]
        return places

    def _rounRobin(topo, cluster):
        i = 0
        places = {}
        nodes = topo.hosts() + topo.switches()
        for node in nodes:
            places[node] = cluster[i%len(cluster)]
            i = i + 1
        return places

    print ("# compute mapping")
    from distrinet.dummymapper import DummyMapper
    if options.single:
        places = _singleMachine(topo, cluster)
    else:
#        places = _twoMachines(topo, cluster)
        places = _rounRobin(topo, cluster)

    mapper = DummyMapper(places=places)

    print ("mapping:", mapper.places)

    print ("JUMP!",jump)
    mn = Distrinet(
            topo=topo,
            switch=switch, host=host, #controller=controller,
            link=link,
            ipBase=ipBase,
            adminIpBase=adminIpBase,
            inNamespace=inNamespace,
            xterms=xterms, autoSetMacs=autoSetMacs,
            autoStaticArp=autoSetMacs, autoPinCpus=autoPinCpus,
            listenPort=listenPort, build=build, jump=jump, master=master, mapper=mapper,
            user=user,
            client_keys=client_keys,
            waitConnected=waitConnected)

    from distrinet.cloud.assh import ASsh
    masterSsh = ASsh(loop=mn.loop, host=master, username=user, bastion=jump, client_keys=client_keys)
    masterSsh.connect()
    masterSsh.waitConnected()
    masterSsh.cmd("nohup /usr/bin/ryu-manager --verbose /usr/lib/python2.7/dist-packages/ryu/app/simple_switch_13.py >& controller.dat &")
    mn.addController(name='c0', controller=LxcRemoteController, ip="192.168.0.1", port=6633 )

    mn.build()
    print (dir (mn))
    print (mn.hosts)
    mn.start()

    elapsed = float( time.time() - start )
    print ( 'completed in %0.3f seconds\n' % elapsed )

    print ("Wait 10s for LLDP and STP to do their magic")
    sleep(10)
    
    print ("# populate /etc/hosts")
    makeHosts(topo=topo, net=mn, wait=False)
    for host in mn.hosts:
        host.waitOutput()


    print ("# configure bottleneck link to 1Gbps")
    s1=mn.get('s1')
    s2=mn.get('s2')

    links = s1.connectionsTo(s2)

    srcLink = links[0][0]
    dstLink = links[0][1]

    srcLink.config(**{ 'bw' : 1000})
    dstLink.config(**{ 'bw' : 1000})

#    from mininet.cli import CLI
#    CLI(mn)

##################
#############
    def aliasMaster(topo, net):
        master = getHadoopMaster(topo)
        print ("The master is {} ".format(master))

        lines = []
        line = "{} {}".format(net.nameToNode[master].IP(), "master")
        lines.append(line)
        for host in topo.hosts():
            lines.append("{} {}".format(net.nameToNode[host].IP(), host))
        print (" >>> {}".format(lines))
        for host in topo.hosts():
            print ("\t Adding to host {}".format(lines))
            makeFile(net=net, host=host, lines=lines, filename="/etc/hosts", overwrite=False)

    def makeMasters(topo, net):
        """Generate the etc/hadoop/masters file on all the masters
        """
        masters = list()

        for host in topo.hosts():
            if "role" in topo.nodeInfo(host).keys() and topo.nodeInfo(host)["role"] == "master":
                masters.append(host)

        # Execute the command to build etc/hadoop/masters on each master
        for master in masters:
            makeFile(net, master, masters, "/root/hadoop-2.7.6/etc/hadoop/masters", overwrite=False)

    from distrinet.topodc import (HadoopDumbbellTopo, getHadoopMaster)

    def makeSlaves(topo, net):
        """ Generate the etc/hadoop/slaves file on all hosts
        """
        cluster = list()
        slaves = list()

        hosts = topo.hosts()
        for host in hosts:
            if "role" in topo.nodeInfo(host).keys():
                if topo.nodeInfo(host)["role"] == "slave":
                    slaves.append(host)
                    cluster.append(host)
                elif topo.nodeInfo(host)["role"] == "master":
                    cluster.append(host)

        # Execute the command to build etc/hadoop/slaves on each host
        for host in cluster:
            makeFile(net, host, slaves, "/root/hadoop-2.7.6/etc/hadoop/slaves", overwrite=False)
##############

    aliasMaster(topo=topo, net=mn)
    print ("# populate etc/hadoop/masters")
    makeMasters(topo=topo, net=mn)

    print
    print ("# populate etc/hadoop/slaves")
    makeSlaves(topo=topo, net=mn)

    hm = getHadoopMaster(topo)
    hadoopMasterNode = mn.nameToNode[hm]

    print ("# Start Hadoop in the cluster")
    print ("# Format HDFS")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hdfs namenode -format -force"'))

    print ("# Launch HDFS")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/sbin/start-dfs.sh"'))

    print ("# Launch YARN")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/sbin/start-yarn.sh"'))

    print ("# Time for benchmarks!")
    print ("# Create a directory for the user")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hdfs dfs -mkdir -p /user/root"'))
    sleep(2)

    print ("")
    print ("# Compute PI")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hadoop jar  /root/hadoop-2.7.6/share/hadoop/mapreduce/hadoop-mapreduce-examples-2.7.6.jar pi 20 100"'))

    print ("")
    print ("# Teragen")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hadoop jar  /root/hadoop-2.7.6/share/hadoop/mapreduce/hadoop-mapreduce-examples-2.7.6.jar teragen 1000000 bench.tera"'))
    print ("# Terasort")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hadoop jar  /root/hadoop-2.7.6/share/hadoop/mapreduce/hadoop-mapreduce-examples-2.7.6.jar terasort bench.tera bench.tera.out"'))
    print ("# Teravalidate")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hadoop jar  /root/hadoop-2.7.6/share/hadoop/mapreduce/hadoop-mapreduce-examples-2.7.6.jar teravalidate bench.tera.out bench.tera.validate"'))


    print ("")
    print ("# Wordcount")
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hadoop dfs -mkdir bench.wordcount"'))
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hadoop dfs -copyFromLocal /etc/hosts bench.wordcount/hosts"'))
    print (hadoopMasterNode.cmd('bash -c "/root/hadoop-2.7.6/bin/hadoop jar  /root/hadoop-2.7.6/share/hadoop/mapreduce/hadoop-mapreduce-examples-2.7.6.jar wordcount bench.wordcount/hosts bench.wordcount bench.wordcount.out"'))
##################


    print ("# stopping the experiment")
    mn.stop()
    mn.loop.stop()