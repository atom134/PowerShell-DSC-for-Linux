#!/usr/bin/env python
#============================================================================
# Copyright (C) Microsoft Corporation, All rights reserved.
#============================================================================

import os
import imp
import re
import codecs
from functools import reduce
protocol = imp.load_source('protocol', '../protocol.py')
nxDSCLog = imp.load_source('nxDSCLog', '../nxDSCLog.py')

LG = nxDSCLog.DSCLog

rsyslog_conf_path = '/etc/rsyslog.conf'
rsyslog_inc_conf_path = '/etc/rsyslog.d/95-omsagent.conf'
syslog_ng_conf_path = '/etc/syslog-ng/syslog-ng.conf'
sysklog_conf_path='/etc/syslog.conf'
oms_syslog_ng_conf_path = '/etc/opt/omi/conf/omsconfig/syslog-ng-oms.conf'
oms_rsyslog_conf_path = '/etc/opt/omi/conf/omsconfig/rsyslog-oms.conf'
conf_path = ''


def init_vars(SyslogSource, WorkspaceID):
    global conf_path
    for source in SyslogSource:
        if source['Severities'] is not None:
            if 'value' in dir(source['Severities']):
                source['Severities'] = source['Severities'].value
        if 'value' in dir(source['Facility']):
            source['Facility'] = source['Facility'].value
    if os.path.exists(rsyslog_conf_path):
        conf_path = oms_rsyslog_conf_path
    elif os.path.exists(syslog_ng_conf_path):
        conf_path = oms_syslog_ng_conf_path
    else:
        LG().Log('ERROR', 'Unable to find OMS config files.')
        raise Exception('Unable to find OMS config files.')
    LG().Log('INFO', 'Config file is ' + conf_path + '.')


def Set_Marshall(SyslogSource, WorkspaceID):
    if os.path.exists(sysklog_conf_path):
        LG().Log('ERROR', 'Sysklogd is unsupported.')
        return [0]
    init_vars(SyslogSource, WorkspaceID)
    retval = Set(SyslogSource, WorkspaceID)
    if retval is False:
        retval = [-1]
    else:
        retval = [0]
    return retval


def Test_Marshall(SyslogSource, WorkspaceID):
    if os.path.exists(sysklog_conf_path):
        LG().Log('ERROR', 'Sysklogd is unsupported.')
        return [0]
    init_vars(SyslogSource, WorkspaceID)
    return Test(SyslogSource, WorkspaceID)


def Get_Marshall(SyslogSource, WorkspaceID):
    if os.path.exists(sysklog_conf_path):
        LG().Log('ERROR', 'Sysklogd is unsupported.')
        return 0, {'SyslogSource':protocol.MI_InstanceA([])}
    arg_names = list(locals().keys())
    init_vars(SyslogSource, WorkspaceID) # TODO resolve; we can assume here that WorkspaceID has value like SyslogSource does and nxPackage uses things here https://github.com/Microsoft/PowerShell-DSC-for-Linux/blob/master/Providers/Scripts/2.6x-2.7x/Scripts/nxPackage.py#L348
    retval = 0
    NewSource, NewWorkspaceID = Get(SyslogSource, WorkspaceID)
    for source in NewSource:
        if source['Severities'] is not None:
            source['Severities'] = protocol.MI_StringA(source['Severities'])
        source['Facility'] = protocol.MI_String(source['Facility'])
    SyslogSource = protocol.MI_InstanceA(NewSource)
    WorkspaceID = protocol.MI_String(NewWorkspaceID)
    retd = {}
    ld = locals()
    for k in arg_names:
        retd[k] = ld[k]
    return retval, retd


def Set(SyslogSource, WorkspaceID):
    if Test(SyslogSource, WorkspaceID) == [0]:
        return [0]
    if conf_path == oms_syslog_ng_conf_path:
        ret = UpdateSyslogNGConf(SyslogSource, WorkspaceID)
    else:
        ret = UpdateSyslogConf(SyslogSource, WorkspaceID)
    if ret:
        ret = [0]
    else:
        ret = [-1]
    return ret


def Test(SyslogSource, WorkspaceID):
    if conf_path == oms_syslog_ng_conf_path:
        NewSource, NewWorkspaceID = ReadSyslogNGConf(SyslogSource, WorkspaceID)
    else:
        NewSource, NewWorkspaceID = ReadSyslogConf(SyslogSource, WorkspaceID)
    # TODO figure out how to test workspace id given that we may be able to extract it from omsagent.conf
    # TODO also figure out if I should be parsing the syslogconf any differently
    if WorkspaceID != NewWorkspaceID:
        return [-1]
    SyslogSource=sorted(SyslogSource, key=lambda k: k['Facility'])
    for d in SyslogSource:
        found = False
        if 'Severities' not in d.keys() or d['Severities'] is None or len(d['Severities']) is 0:
            d['Severities'] = ['none']  # redundant?
        d['Severities'].sort()
    NewSource=sorted(NewSource, key=lambda k: k['Facility'])
    for n in NewSource:
        n['Severities'].sort()
    if SyslogSource != NewSource:
        return [-1]
    return [0]


def Get(SyslogSource, WorkspaceID):
    if conf_path == oms_syslog_ng_conf_path:
        NewSource, NewWorkspaceID = ReadSyslogNGConf(SyslogSource, WorkspaceID)
    else:
        NewSource, NewWorkspaceID = ReadSyslogConf(SyslogSource, WorkspaceID)
    for d in NewSource:
        if d['Severities'] == ['none']:
            d['Severities'] = []
    return NewSource, NewWorkspaceID


def ReadSyslogConf(SyslogSource, WorkspaceID):
    # TODO find the right section in the conf for the WorkspaceID and return it
    out = []
    txt = ''
    if len(SyslogSource) == 0:
        return out
    if not os.path.exists('/etc/rsyslog.d'):
        try:
            txt = codecs.open(rsyslog_conf_path, 'r', 'utf8').read()
            LG().Log('INFO', 'Successfully read ' + rsyslog_conf_path + '.')
        except:
            LG().Log('ERROR', 'Unable to read ' + rsyslog_conf_path + '.')
    else:
        src_conf_path = conf_path
        if os.path.exists(rsyslog_inc_conf_path):
            src_conf_path = rsyslog_inc_conf_path
        try:
            txt = codecs.open(src_conf_path, 'r', 'utf8').read()
            LG().Log('INFO', 'Successfully read ' + src_conf_path + '.')
        except:
            LG().Log('ERROR', 'Unable to read ' + src_conf_path + '.')
            return out
    workspace = str(WorkspaceID)  # should match regex ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})
    workspace_search = r'^# OMS Syslog collection for workspace (' + workspace + ')\n(.*@[0-9\.\:]*\n){1,20}$'
    facility_search = r'
# TODO working idea: r'^# OMS Syslog collection for workspace ([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\n((.*?)@[0-9\.\:]*\n){1,20}'
    workspace_re = re.compile(workspace_search, re.M)
    facility_search = r'^(.*?)@.*?25224$' #TODO change this to be more dynamic, because we can't assume that the primary workspace hasn't been removed and 25224 is freed
    facility_re = re.compile(facility_search, re.M)
    for line in facility_re.findall(txt):
        l = line.replace('=', '')
        l = l.replace('\t', '').split(';')
        sevs = []
        fac = l[0].split('.')[0]
        for sev in l:
            sevs.append(sev.split('.')[1])
        out.append({'Facility': fac, 'Severities': sevs})
    return out  # TODO return workspaceID as well (format? type?)


def UpdateSyslogConf(SyslogSource, WorkspaceID): #TODO update this to write in the workspace ID
    # TODO: If this configuration is (conceptually) getting passed from the workspace to the agent, then I'm only going to have a single workspace ID to deal with
    # TODO: Find my workspace ID in the conf file and ONLY replace that section of the conf in this method
    arg = ''
    if 'rsyslog' in conf_path:
        if os.path.exists('/etc/rsyslog.d'):
            txt = ''
        elif os.path.exists(rsyslog_conf_path):
            arg = '1'
            try:
                txt = codecs.open(rsyslog_conf_path, 'r', 'utf8').read()
                LG().Log(
                    'INFO', 'Successfully read ' + rsyslog_conf_path + '.')
            except:
                LG().Log('ERROR', 'Unable to read ' + rsyslog_conf_path + '.')
    facility_search = r'(#facility.*?\n.*?25224\n)|(^[^#].*?25224\n)'
    facility_re = re.compile(facility_search, re.M)
    for t in facility_re.findall(txt):
        for r in t:
            txt = txt.replace(r, '')
    for d in SyslogSource:
        facility_txt = '#facility = ' + d['Facility'] + '\n'
        for s in d['Severities']:
            facility_txt += d['Facility'] + '.=' + s + ';'
        facility_txt = facility_txt[0:-1] + '\t@127.0.0.1:25224\n'
        txt += facility_txt
    try:
        codecs.open(conf_path, 'w', 'utf8').write(txt)
        LG().Log(
            'INFO', 'Created omsagent rsyslog configuration at ' + conf_path + '.')
    except:
        LG().Log(
            'ERROR', 'Unable to create omsagent rsyslog configuration at ' + conf_path + '.')
        return False
    if os.system('sudo /opt/microsoft/omsconfig/Scripts/OMSRsyslog.post.sh ' + arg) == 0:
        LG().Log('INFO', 'Successfully executed OMSRsyslog.post.sh.')
    else:
        LG().Log('ERROR', 'Error executing OMSRsyslog.post.sh.')
        return False
    return True


def ReadSyslogNGConf(SyslogSource, WorkspaceID):
    #TODO
    out = []
    txt = ''
    try:
        txt = codecs.open(syslog_ng_conf_path, 'r', 'utf8').read()
        LG().Log('INFO', 'Successfully read ' + syslog_ng_conf_path + '.')
    except:
        LG().Log('ERROR', 'Unable to read ' + syslog_ng_conf_path + '.')
        return out
    facility_search = r'^filter f_(?P<facility>.*?)_oms.*?level\((?P<severities>.*?)\)'
    facility_re = re.compile(facility_search, re.M)
    for s in facility_re.findall(txt):
        sevs = []
        if len(s[1]):
            if ',' in s[1]:
                sevs = s[1].split(',')
            else:
                sevs.append(s[1])
        out.append({'Facility': s[0], 'Severities': sevs})
    return out  # TODO update to return WorkspaceID as well (format? type?)


def UpdateSyslogNGConf(SyslogSource, WorkspaceID):
    #TODO
    txt = ''
    try:
        txt = codecs.open(syslog_ng_conf_path, 'r', 'utf8').read()
        LG().Log('INFO', 'Successfully read ' + syslog_ng_conf_path + '.')
    except:
        LG().Log('ERROR', 'Unable to read ' + syslog_ng_conf_path + '.')
        return False
    facility_search = r'(\n+)?(#OMS_Destination.*?25224.*?\n)?(\n)?(#OMS_facility.*?filter.*?_oms.*?log.*destination.*?\n)'
    facility_re = re.compile(facility_search, re.M | re.S)
    txt = facility_re.sub('', txt)
    txt += '\n\n#OMS_Destination\ndestination d_oms { udp("127.0.0.1" port(25224)); };\n'
    for d in SyslogSource:
        if 'Severities' not in d.keys() or d['Severities'] is None or len(d['Severities']) is 0:
            facility_txt = ''
        else:
            facility_txt = '\n#OMS_facility = ' + d['Facility'] + '\n'
            sevs = reduce(lambda x, y: x + ',' + y, d['Severities'])
            facility_txt += 'filter f_' + \
                d['Facility'] + \
                '_oms { level(' + sevs + ') and facility(' + d[
                    'Facility'] + '); };\n'
            facility_txt += 'log { source(src); filter(f_' + d[
                'Facility'] + '_oms); destination(d_oms); };\n'
            txt += facility_txt
    try:
        codecs.open(conf_path, 'w', 'utf8').write(txt)
        LG().Log(
            'INFO', 'Created omsagent syslog-ng configuration at ' + conf_path + '.')
    except:
        LG().Log(
            'ERROR', 'Unable to create omsagent syslog-ng configuration at ' + conf_path + '.')
        return False
    if os.system('sudo /opt/microsoft/omsconfig/Scripts/OMSSyslog-ng.post.sh') == 0:
        LG().Log('INFO', 'Successfully executed OMSSyslog-ng.post.sh.')
    else:
        LG().Log('ERROR', 'Error executing OMSSyslog-ng.post.sh.')
        return False
    return True
