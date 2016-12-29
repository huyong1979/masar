#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Created on Tue Nov 15 11:08:09 2016

@author: yhu
"""
import sys
from cothread.catools import caget 
import sqlite3

if len(sys.argv) != 3:
    print "Use command like this: %s pv-list-file config_id"%sys.argv[0]
    sys.exit()
pvListFile = sys.argv[1]
configId = int(sys.argv[2])

db = sqlite3.connect('/home/yhu/masar_backup/masar-test.db')
cursor = db.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print "there are %d tables in MASAR: "%len(tables)
print tables

# add PVs to pv table
cursor.execute("select sql from sqlite_master where type='table' and name = 'pv';")
pvTable = cursor.fetchall()
print "The schema of the 'pv' table: "
print pvTable
cursor.execute("SELECT * FROM pv WHERE pv_id = (SELECT MAX(pv_id) FROM pv);")
maxPvId = cursor.fetchall()
maxPvIdNum = maxPvId[0][0]
print "pv_id of the most recently added PV: "
print maxPvId
pvList = []
with open(pvListFile) as fd:
    lines = fd.readlines()
    for line in lines:
        pvList.append(line.strip('\n'))
#print pvList
disConnectedPvs = 0
results = caget(pvList, throw=False)
for result in results:
    if result.ok != True:
        disConnectedPvs += 1
        print "%s is disconnected. So exit..."%result.name
if disConnectedPvs > 0:
    sys.exit()     
rowsAddedToPvTable = []  
for i in range(len(pvList)):
    rowsAddedToPvTable.append((maxPvIdNum+i+1, unicode(pvList[i]), None))
#print rowsAddedToPvTable[:10]
cursor.executemany('INSERT INTO pv VALUES (?,?,?)', rowsAddedToPvTable)
#db.commit()
cursor.execute("SELECT * FROM pv WHERE pv_id = (SELECT MAX(pv_id) FROM pv);")
maxPvId2 = cursor.fetchall()
print "After adding new PVs, max pv_id is: "
print maxPvId2

#get pv_group_id from service_config_id
cursor.execute("SELECT * FROM sqlite_master where type='table' and name = 'pvgroup__serviceconfig';")
table2 = cursor.fetchall()
print "The schema of the 'pvgroup__serviceconfig' table: "
print table2
cursor.execute("SELECT * FROM pvgroup__serviceconfig WHERE service_config_id = %d;"%configId)
pvGroup2ConfigId = cursor.fetchall()
print pvGroup2ConfigId
pvGroupId = pvGroup2ConfigId[0][1]
print "configId %d: pvGroupId %d"%(configId, pvGroupId)

#assign PVs to pv_group
cursor.execute("select * from sqlite_master where type='table' and name = 'pv__pvgroup';")
table3 = cursor.fetchall()
print "The schema of the 'pv__pvgroup' table: "
print table3
cursor.execute("SELECT * FROM pv__pvgroup WHERE pv__pvgroup_id = (SELECT MAX(pv__pvgroup_id) FROM pv__pvgroup);")
maxPv2PvGroupId = cursor.fetchall()
print "pv__pvgroup_id of the most recently added PV to pvGroup: "
print maxPv2PvGroupId
maxPv2PvGroupIdNum = maxPv2PvGroupId[0][0]
#print maxPv2PvGroupIdNum
rowsAddedToPv2PvGroupTable = []  
for i in range(len(pvList)):
    rowsAddedToPv2PvGroupTable.append((maxPv2PvGroupIdNum+i+1, maxPvIdNum+i+1, pvGroupId))
#print rowsAddedToPv2PvGroupTable[:10]
cursor.executemany('INSERT INTO pv__pvgroup VALUES (?,?,?)', rowsAddedToPv2PvGroupTable)

db.commit()