#!/usr/bin/env python
'''
Created on Dec 1, 2011

@Original author: shengb
@co-author: Yong Hu (yhu@bnl.gov)
'''

from __future__ import division
from __future__ import print_function
#from __future__ import unicode_literals

import os, sys, time, datetime, re, fnmatch, imp, traceback, platform, errno

from PyQt4.QtGui import (QApplication, QMainWindow, QMessageBox, QTableWidgetItem, QTableWidget,
                        QFileDialog, QColor, QBrush, QTabWidget, QShortcut, QKeySequence,
                        QDialog, QGridLayout, QLineEdit, QPushButton, QLabel, QDialogButtonBox)
from PyQt4.QtCore import (QDateTime, Qt, QString, QObject, SIGNAL, QThread, QEventLoop)
#import PyQt4.QTest as QTest

try:
    _fromUtf8 = QString.fromUtf8
except AttributeError:
    _fromUtf8 = lambda s: s

if sys.version_info[:2]>=(2,7):
    from collections import OrderedDict as odict
else:
    print ('Python version 2.7 or higher is needed.')
    sys.exit()

import ui_masar
import commentdlg
from showarrayvaluedlg import ShowArrayValueDlg
from selectrefsnapshotdlg import ShowSelectRefDlg
from finddlg import FindDlg
from verifysetpoint import VerifySetpoint
from gradualput import GradualPut
import getmasarconfig 
masarConfigDict = getmasarconfig.getmasarconfig()
#print(masarConfigDict)
try:
    imp.find_module('pyOlog')
    if str(masarConfigDict["Olog"]["use"]) == 'True':
        pyOlogExisting = True
    else:
        pyOlogExisting = False
except ImportError:
    pyOlogExisting = False

        
import masarclient.masarClient as masarClient
from masarclient.channelRPC import epicsExit 

__version__ = "1.0.1"

def usage():
    print("""usage: masar.py [option]

command option:
-h  --help       help

masar.py v {0}. Copyright (c) 2011 Brookhaven National Laboratory. All rights reserved.
""".format(__version__))
    sys.exit()

# import this last to avoid import error on some platform and with different versions. 
os.environ["EPICS_CA_MAX_ARRAY_BYTES"] = '40000000'
import cothread
import cothread.catools as cav3
from cothread import Sleep
#qtapp = cothread.iqt()

#class masarUI(QMainWindow, ui_masar.Ui_masar, QTabWidgetExt):
class masarUI(QMainWindow, ui_masar.Ui_masar):
    severityDict= {0: 'NO_ALARM',
                   1: 'MINOR_ALARM',
                   2: 'MAJOR_ALARM',
                   3: 'INVALID_ALARM',
                   4: 'ALARM_NSEV'
    }
    
    alarmDict = { 0: 'NO_ALARM',
                 1: 'READ_ALARM',
                 2: 'WRITE_ALARM',
                 3: 'HIHI_ALARM',
                 4: 'HIGH_ALARM',
                 5: 'LOLO_ALARM',
                 6: 'LOW_ALARM',
                 7: 'STATE_ALARM',
                 8: 'COS_ALARM',
                 9: 'COMM_ALARM',
                 10: 'TIMEOUT_ALARM',
                 11: 'HW_LIMIT_ALARM',
                 12: 'CALC_ALARM',
                 13: 'SCAN_ALARM',
                 14: 'LINK_ALARM',
                 15: 'SOFT_ALARM',
                 16: 'BAD_SUB_ALARM',
                 17: 'UDF_ALARM',
                 18: 'DISABLE_ALARM',
                 19: 'SIMM_ALARM',
                 20: 'READ_ACCESS_ALARM',
                 21: 'WRITE_ACCESS_ALARM',
                 22: 'ALARM_NSTATUS'
    }

    def __init__(self, channelname='masarService', parent=None):
        super(masarUI, self).__init__(parent)
        self.setupUi(self)
        self.__setDateTime() 
        #the following 3 lines have to be before self.__initSystemCombox()        
        self.__service = 'masar'
        self.mc = masarClient.client(channelname) 
        self.currentConfigFilter = str(self.configFilterLineEdit.text())  
        #self.currentRestoreFilter = str(self.restoreFilterLineEdit.text()) 
        self.currentPvFilter = str(self.pvFilterLineEdit.text()) 
        self.pvFilterLineEdit.returnPressed.connect(self.searchPV)
        self.snapshotIdLineEdit.returnPressed.connect(self.retrieveSnapshotById)
        
        self.__initSystemCombox()   
        time.sleep(1.0)
        
        self.eventConfigFilter = str(self.eventFilterLineEdit.text())
        self.authorText = str(self.authorTextEdit.text())  
        self.UTC_OFFSET_TIMEDELTA = datetime.datetime.utcnow() - datetime.datetime.now()
        self.time_format = "%Y-%m-%d %H:%M:%S"
        self.tabWindowDict = {'comment': self.commentTab}# comment, preview, compare, filter
        self.e2cDict = {} # event to config dict; see retrieveEventData(): self.e2cDict[eid] = [cid, desc,configName]
        self.pv4cDict = {} # pv name list for each selected configuration / eid
        self.data4eid = {} # snapshot data for eventId: 'filter' is an eventID  
        self.arrayData = {} # store all array data
        self.previewId = None
        self.previewConfName = None
        self.isPreviewSaved = False
        self.compareLiveWithMultiSnapshots = False
        self.compareSnapshotsTableKeys = []
        self.eventIds = []
        self.origID = ""
        self.passWd = ''
        self.timeAtRetrieveSnapshot = 0
        self.timeAtSetSnapshotTabWindow = 0
        #self.shortcut4Find = None
        self.dlgFlag = [0]
        self.verifyWindowDict = {}#
        
        # set bad pv row to grey: bad pvs means that they were bad when the snapshot was taken
        self.brushbadpv = QBrush(QColor(128, 128, 128))
        self.brushbadpv.setStyle(Qt.SolidPattern)
        # set currently disconnected pv row to pink
        self.brushdisconnectedpv = QBrush(QColor(255, 0, 255))
        self.brushdisconnectedpv.setStyle(Qt.SolidPattern)
        # DBR_TYPE definition
        #define DBF_STRING  0
        #define DBF_INT     1
        #define DBF_SHORT   1
        #define DBF_FLOAT   2
        #define DBF_ENUM    3
        #define DBF_CHAR    4
        #define DBF_LONG    5
        #define DBF_DOUBLE  6
        self.epicsLong   = [1, 4, 5]
        self.epicsString = [0, 3]
        self.epicsDouble = [2, 6]
        self.epicsNoAccess = [7]
        self.userID = os.popen('whoami').read()[:-1]  
        dirPath = os.path.dirname(os.path.abspath(__file__))
        self.goldenDataFilePath = dirPath + '/goldenSnapshotData/'        
        #automatically fetch all configs at startup. This action should be quick
        self.fetchConfigAction()
        time.sleep(1.0)

    def __setDateTime(self):
        self.eventStartDateTime.setDateTime(QDateTime.currentDateTime())
        self.eventEndDateTime.setDateTime(QDateTime.currentDateTime())   
 
 
#********* Start of Config Table ******************************************************************  
    def __initSystemCombox(self):
        self.systemCombox.addItem(_fromUtf8(""))
        self.systemCombox.setItemText(0, "all")
        results = self.getSystemList()
        if results:
            for i in range(len(results)):
                self.systemCombox.addItem(_fromUtf8(""))
                self.systemCombox.setItemText(i+1, results[i])
        self.system = str(self.systemCombox.currentText())

    def getSystemList(self):
        try:
            return self.mc.retrieveSystemList()
        except:
            QMessageBox.warning(self,
            "Warning",
            "Cannot connect to MASAR server to getSystemList.\nPlease check the serviceName, etc.")

            return
            
    def systemComboxChanged(self, qstring):
        """
        see ui_masar.py(.ui)
        QObject.connect(self.systemCombox, 
                QtCore.SIGNAL(_fromUtf8("currentIndexChanged(QString)")), masar.systemComboxChanged)
        """
        self.system = str(qstring)
        self.fetchConfigAction()
    
    def configFilterChanged(self):
        """
        see ui_masar.py(.ui) 
        QtCore.QObject.connect(self.configFilterLineEdit, 
                QtCore.SIGNAL(_fromUtf8("textChanged(QString)")), masar.configFilterChanged)
        """
        self.currentConfigFilter = str(self.configFilterLineEdit.text())
        self.fetchConfigAction()
        
    def fetchConfigAction(self):
        """
        see ui_masar.py(.ui)
        QtCore.QObject.connect(self.fetchConfigButton, 
                QtCore.SIGNAL(_fromUtf8("clicked()")), masar.fetchConfigAction)
        """   
        self.setConfigTable()
        self.configTableWidget.resizeColumnsToContents()    
                
    def setConfigTable(self):
        """
        automatically get a list of snapshots if any config is selected by mouse or keyboard
        interesting: fetchEventAction() is called twice whenever config(s) is selected  
        """
        reorderedData = odict([('Config Name', []), ('CID', []), ('Description', []), \
                               ('Date', []), ('Status', []), ('Version', [])]) 
        data = self.retrieveConfigData()
        if not data:
            QMessageBox.warning(self, "Waring", "Can't get Configuration list")  
            return        
        if len(data['CID']) == 0:
            return  
        #print("\nsetConfigTable")# this is printed twice if no "return" above, why?
        #print(data)
        confOrder = []
        try:
            confOrderStr = str(masarConfigDict["Order"]["conf_order"])
            #print("confOrderStr:%s"%confOrderStr)
            confOrder = [int(conf) for conf in confOrderStr.split() if conf.isdigit()]
        except:
            pass
        #print(confOrder)
        #print(data['Id'])
        confOrderSet = set(confOrder)
        if confOrderSet and confOrderSet.issubset(set(data['CID'])):
            #print("confOrder is a subset")
            for cf in confOrder:
                reorderedData['Config Name'].append(data['Config Name'][list(data['CID']).index(cf)])
                reorderedData['CID'].append(cf)
                reorderedData['Description'].append(data['Description'][list(data['CID']).index(cf)])
                reorderedData['Date'].append(data['Date'][list(data['CID']).index(cf)])
                reorderedData['Status'].append(data['Status'][list(data['CID']).index(cf)])
                reorderedData['Version'].append(data['Version'][list(data['CID']).index(cf)])               
            confL = list(set(data['CID']).difference(confOrderSet))
            confL.sort(reverse=True)
            #print(confL)  
            for cf in confL:
                reorderedData['Config Name'].append(data['Config Name'][list(data['CID']).index(cf)])
                reorderedData['CID'].append(cf)
                reorderedData['Description'].append(data['Description'][list(data['CID']).index(cf)])
                reorderedData['Date'].append(data['Date'][list(data['CID']).index(cf)])
                reorderedData['Status'].append(data['Status'][list(data['CID']).index(cf)])
                reorderedData['Version'].append(data['Version'][list(data['CID']).index(cf)])              
            data = reorderedData
            #print(data['CID'])
            #have to disable sorting, then enable sorting
            self.configTableWidget.setSortingEnabled(False)
            self.setTable(data, self.configTableWidget)
            self.configTableWidget.sortByColumn(4,0)
            self.configTableWidget.setSortingEnabled(True)
        else:
            #print("not a subset")
            self.configTableWidget.setSortingEnabled(False)
            self.setTable(data, self.configTableWidget)
            self.configTableWidget.sortByColumn(3,1)
            self.configTableWidget.sortByColumn(4,0)
            self.configTableWidget.setSortingEnabled(True)
        #print(reorderedData)
        #signal cellClicked or itemClicked covers single click and double click
        #signal cellActivated seems equal to double click
        #signal itemSelectionChanged is the best: one can use keyboard to select table row
        QObject.connect(self.configTableWidget, 
                        SIGNAL(_fromUtf8("itemSelectionChanged()")),self.fetchEventAction)
                        #SIGNAL(_fromUtf8("cellClicked (int,int)")),self.fetchEventAction)
                        #SIGNAL(_fromUtf8("itemClicked (QTableWidgetItem *)")),self.fetchEventAction)
        #QObject.connect(self.configTableWidget, 
                        #SIGNAL(_fromUtf8("cellActivated (int,int)")),self.fetchEventAction)
        #QObject.connect(self.configTableWidget, 
        #SIGNAL(_fromUtf8("cellPressed (int,int)")),self.eventTableWidget.clearContents)
        QObject.connect(self.configTableWidget, 
                SIGNAL(_fromUtf8("itemSelectionChanged()")),lambda: self.resizeSplitter(0))    

    def retrieveConfigData(self):
        data = odict()

        params = {"system": self.system,
                  "servicename": self.__service,
                  "configname": self.currentConfigFilter}
        try:
            rpcResult = self.mc.retrieveServiceConfigs(params)
            utctimes = rpcResult[3]
            config_ts = []
            for ut in utctimes:
                ts = str(datetime.datetime.fromtimestamp(time.mktime(time.strptime(ut, self.time_format))) 
                         - self.UTC_OFFSET_TIMEDELTA)
                config_ts.append(ts)

        except:
            print("%s: Fatal error happened during retrieving Configs"%datetime.datetime.now())
            QMessageBox.warning(self,
                                "Warning",
                                "Fatal error happened during retrieving configurations!")       
            import atexit
            atexit._run_exitfuncs()
            epicsExit()
            sys.exit()#should we quit right away?
            #return False
        
        if not rpcResult:
            return False
        
        data['Config Name'] = rpcResult[1]
        data['CID'] = rpcResult[0]
        data['Description'] = rpcResult[2]
        data['Date'] = config_ts
        data['Status'] = rpcResult[5]
        data['Version'] = rpcResult[4]     
        return data
    
    def setTable(self, data, table):
        """
        Set data view.
        The data has to be an ordered dictionary, and table is a QtGui.QTableWidget
        Here is an example to construct an ordered dictionary.
        """
        #print(data)
        #reorderedData = odict()        
        if data:
            length = len(data.values()[0])
        else:
            print ('data is empty, exit.')
            return
        for i in range(1, len(data.values())):
            if length != len(data.values()[i]):
                QMessageBox.warning(self,
                                    "Warning",
                                    "Data length are not consistent.")

                return

        if isinstance(data, odict) and isinstance(table, QTableWidget):
            # Removes all items in the view, and also all selections
            #table.setSortingEnabled(False)
            table.clear()
            nrows = len(data.values()[0])
            ncols = len(data)
            table.setRowCount(nrows)
            table.setColumnCount(ncols)            
            table.setHorizontalHeaderLabels(data.keys())
            
            n = 0
            for key in data:
                m = 0
                for item in data[key]:
                    if not isinstance(item, basestring):
                        item = str(item)
                    if item:
                        newitem = QTableWidgetItem(item)
                        newitem.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable)
                        table.setItem(m, n, newitem)
                    m += 1
                n += 1
                
            #table.setSortingEnabled(True)    
        else:
            raise "error occurred in setTable(self, data, table)"
 
    def resizeSplitter(self, tableID):
        #h = int(self.eventTableWidget.height())
        #self.fetchSnapshotButton.resize(700,282)
        if tableID == 1:
            self.splitter.setSizes([600,900])
        if tableID == 0:
            self.splitter.setSizes([600,900])
#********* End of Config Table ********************************************************************

    def createNewTableWidget(self, eventID, label):
        """
        types of tables in snapshotTab: comment(Welcome page), ordinary(double-click on event table), 
        preview, compare, filter
        """
        if self.tabWindowDict.has_key(str(eventID)):
            tableWidget = self.tabWindowDict[str(eventID)]
        else:
            tableWidget = QTableWidget()
            self.tabWindowDict[str(eventID)] = tableWidget
            QObject.connect(tableWidget, SIGNAL(_fromUtf8("cellDoubleClicked (int,int)")),  
                            self.__showArrayData)
            shortcut4Find = QShortcut(QKeySequence('Ctrl+F'), tableWidget)
            shortcut4Find.activated.connect(self.handleFind)
        
        self.snapshotTabWidget.addTab(tableWidget, label)
        self.snapshotTabWidget.setTabText(self.snapshotTabWidget.count(), label)  
        self.snapshotTabWidget.setCurrentWidget(tableWidget)    
        return tableWidget 
    
    def handleFind(self):
        if self.dlgFlag[0] == 1:#only open one Find dialog
            return
        #print("test find1")
        self.dlgFlag[0] = 1
        #tableWidget = self.snapshotTabWidget.currentWidget()
        tabWidget = self.snapshotTabWidget
        #self.dlgFlag is a list which could be modified inside FindDlg()
        findDlg = FindDlg(tabWidget, self.dlgFlag, self) 
        #dlg = FindDlg(info, self)#have to use 'self' to make QDialog modalless, why?
        #dlg.setModal(False)
        findDlg.show()
        #print("after dlg.show()")
    
#********* Start of Save machine snapshot ********************************************************* 
    def getAuthentication(self):
        #masarConfigDict = getmasarconfig.getmasarconfig()
        #print(masarConfigDict)
        #if masarConfigDict == {}:
        if not masarConfigDict: #empty dict
            return True # no authentication if no file for masar config
        
        if masarConfigDict['LDAP']['existing'] == 'True':
            import ldap  
            from authendlg import AuthenDlg

            userID = self.userID
            #===================================================================
            # #print(os.path.realpath(__file__))
            # dirPath = os.path.dirname(os.path.abspath(__file__))
            # #fd = open('%s/masar.config'%os.environ['PWD'], "r")
            # fd = open('%s/masar.config'%dirPath, "r")
            # #print(fd.readlines())
            # lines = fd.readlines()
            # for line in lines:
            #     if line[:12] == 'ldapExisting':
            #         ldapExisting = line.split('=')[1]                
            #     if line[:10] == 'ldapServer':
            #         ldapServer = line.split('=')[1]
            #     if line[:8] == 'userName':
            #         userName = line.split('==')[1]
            # #print(userName[:-1])
            #===================================================================      
            dlg = AuthenDlg(self.passWd)
            dlg.exec_()
            if dlg.isAccepted:
                self.passWd = dlg.result()      
                #user = userID[:-1]#remove trailing '\n' 
                ldap.protocol_version = 3
                ldap.set_option(ldap.OPT_REFERRALS, 0)
                try:
                    #lp = ldap.initialize("ldap://ldapmaster.cs.nsls2.local:389")
                    lp = ldap.initialize(masarConfigDict['LDAP']['url'])
                    #for NSLS2, cn is admin, must use uid instead
                    #username = "uid=%s,ou=people,dc=nsls2,dc=bnl,dc=gov"%user
                    username = masarConfigDict['LDAP']['username']%userID
                    #print(username)
                    lp.simple_bind_s(username, self.passWd)
                    return True
                except:
                    self.passWd = ""
                    QMessageBox.warning(self, 'Warning', 
'Failed to get anthentication, you may have typed wrong password, try again if you like')   
                    #traceback.print_exc()   
                    return False               
                        
            else:#if dlg.isAccepted:
                return False   
        
        return True#masarConfigDict['LDAP']['existing'] == 'False'
    
        
    def createLogEntry(self, logText, logbookName = None):        
        #masarConfigDict = getmasarconfig.getmasarconfig()
        if not masarConfigDict:
            return  # no authentication if no file for masar config
        
        if pyOlogExisting:        
            userID = self.userID
            try:    
                #import requests
                #print("requests version: %s"%requests.__version__) 
                from pyOlog import OlogClient, Tag, Logbook, LogEntry  
                #if 'https_proxy' in os.environ.keys():
                    #print("unset https_proxy: %s"%(os.environ['https_proxy']))
                    #del os.environ['https_proxy']   
                os.environ["no_proxy"]="web02.cs.nsls2.local,*.cs.nsls2.local,localhost"         
                client = OlogClient(url=str(masarConfigDict['Olog']['url']).strip(),\
                                    username=str(userID).strip(), password=self.passWd)     
                     
                logbookNames=str(masarConfigDict['Olog']['logbookname']).strip().split(',')
                logbooks = []
                for name in logbookNames:
                    logbooks.append(Logbook(name=name))
                    
                client.log(LogEntry(text=logText, owner=userID[:-1], \
                                 #logbooks=[Logbook(name=logbookName, owner='Controls')],\
                                 logbooks=logbooks,\
                                 tags=[Tag(name='MASAR')]))
            except:
                #QMessageBox.warning(self, 'Warning', 
            #'Although failing to create an Olog entry, you are done with your action / command') 
                print("%s: failed to create an Olog entry"%datetime.datetime.now())
                traceback.print_exc()
                      
    def saveMachineSnapshot(self):
        """
        See ui_masar.py(.ui):
        QtCore.QObject.connect(self.saveMachineSnapshotButton, 
                    QtCore.SIGNAL(_fromUtf8("clicked()")), masar.saveMachineSnapshot)
        Purpose: implement one button 'Save Machine ...' to preview live data and then save.
        Challenge: get the pv list for getLiveMachineData(pvList) from the 'config' table
        Solution: get config name --> use retrieveEventData() to get at least one eventId 
                    --> retrieveSnapshot() to get the pv list for that config
        """
        selectedConfig = self.configTableWidget.selectionModel().selectedRows()
        lc = len(selectedConfig)
        if lc != 1:
            QMessageBox.warning(self,
                "Warning",
                "Please select one configuration from the left-top Config Table, and one only.")
            return

        if not self.getAuthentication():
            return
        
        self.saveMachineSnapshotButton.setEnabled(False)
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.previewId = None
        self.previewConfName = None
        
        eventIds = []
        configIds = []
        configNames = []
        disConnectedPVs = []
        
        cname = str(self.configTableWidget.item(selectedConfig[0].row(), 0).text())
        configID = str(self.configTableWidget.item(selectedConfig[0].row(), 1).text())
        configDesc = str(self.configTableWidget.item(selectedConfig[0].row(), 2).text())
        result = self.getMachinePreviewData(cname)
        
        #=======================================================================
        # cid = str(self.configTableWidget.item(selectedConfig[0].row(), 1).text())
        # configIds.append(cid)
        # configNames.append(cname)
        # print(configIds)
        # print(configNames)
        # #eventData = self.mc.retrieveServiceEvents(params)
        # eventData = self.retrieveEventData(configids=configIds, confignames=configNames)
        # print(eventData)
        # print(eventData['Id'])
        # #if eventData == None:
        # if eventData['Id'] == []:
        #     params = {'configname': configNames,
        #               #'servicename': 'masarServiceDevelopment'}
        #               'servicename': 'masar'} 
        #     try:
        #         rpcResult = self.mc.saveSnapshot(params)
        #     except:
        #         QMessageBox.warning(self,"Warning","Exception happened during getting machine preview.")
        #         return False
        #     if not rpcResult:
        #         QMessageBox.warning(self,"Warning","can't save a snapshot.")
        #         return False
        #     #eventid = rpcResult[0]
        #     #pvnames = rpcResult[1]
        #     firstEventId = rpcResult[0]
        # else:          
        #     #print(eventData['Id'])
        #     firstEventId = eventData['Id'][0]
        # 
        # eventIds.append(firstEventId)
        # print(firstEventId) 
        # #print('eventIds:%s'%eventIds)
        # 
        # #params = {'eventid': eventIds}
        # params = {'eventid': str(firstEventId)}
        # rpcResult = self.mc.retrieveSnapshot(params)
        # if rpcResult == None:
        #     QMessageBox.warning(self,"Warning","Except happened when getting machine preview.")
        #     return
        # else:
        #     #print("self.mc.retrieveSnapshot:")
        #     #print(rpcResult)
        #     #have to wait 2 seconds before calling getLiveMachineData() if the snapshot has big data set
        #     QThread.sleep(2)
        #     pvList = list(rpcResult[0])
        #     #print(pvList)
        #     result = self.getLiveMachineData(pvList)
        #     #print(len(result[0]))
        #     #print(result[8])
        #     #print("self.getLiveMachineData:")
        #     #print(result)
        #     if result == None:
        #         QMessageBox.warning(self,"Warning", "can't get machine preview data")
        #         return
        #     else:
        #         self.resizeSplitter(1)
        #         connectedPVs = list(set(pvList) - set(result[8]))
        #         disConnectedPVs = result[8]
        #         #print("total PV:%d; disconnected: %d; connected: %d" %(len(pvList),len(result[8]),len(connectedPVs)))
        #         #v3Result = []
        #         #have to define the length of the list status[]
        #         status = [""]*len(pvList)
        #         severity = [""]*len(pvList)
        #         timestamp = [0]*len(pvList)
        #     
        #         #v3Results = cav3.caget(pvList, timeout=2,format=cav3.FORMAT_TIME, throw=False)
        #         v3Results = cav3.caget(connectedPVs, timeout=2,format=cav3.FORMAT_TIME, throw=False)
        #         #print(len(v3Results))
        #         #v3Result = cav3.caget('LTB-BI{VF:1}Go-Sel',format=cav3.FORMAT_TIME, timeout=1, throw=False)
        #         #print(v3Result.status)
        #         for v3Result in v3Results:
        #             if v3Result.name not in result[0]:
        #                 QMessageBox.warning(self,"Waring","Exception happened when reading data by cav3.caget")
        #                 return
        #             pvIndex = result[0].index(v3Result.name)
        #             if v3Result.ok == True:
        #                 status[pvIndex] = self.alarmDict[v3Result.status]
        #                 severity[pvIndex] = self.severityDict[v3Result.severity] 
        #                 timestamp[pvIndex] = v3Result.timestamp  
        #             else:
        #                 status[pvIndex] = 'UDF_ALARM'
        #                 severity[pvIndex] = 'INVALID_ALARM'
        #                 timestamp[pvIndex] = 0
        #         #print(v3Result[0].value)
        #         data = odict()
        #         data['PV Name'] = result[0]
        #         #data['Status'] = [""]*len(pvList)
        #         data['Status'] = status
        #         data['Severity'] = severity
        #         data['Time stamp'] = timestamp
        #         data['Time stamp (nano)'] = [0]*len(pvList)
        #         data['DBR'] = result[4]
        #         data['S_value'] = result[1]
        #         data['I_value'] = result[3]
        #         data['D_value'] = result[2]
        #         data['isConnected'] = result[5]
        #         data['isArray'] = result[6]
        #         data['arrayValue'] = result[7]
        #         eid = firstEventId
        #=======================================================================
        if result: 
                self.resizeSplitter(1)      
                eid = result[0]
                data = result[1]
                #set self.previewId in saveMachinePreviewAction instead of here
                self.previewId = eid
                self.previewConfName = cname
                self.isPreviewSaved = False
                self.pv4cDict[str(eid)] = data['PV Name']
                self.data4eid[str(eid)] = data
                self.e2cDict[str(self.previewId )] = [configID, configDesc, cname]#needed for configTab
                              
                label = QString.fromUtf8((cname+': Preview: '+str(eid)))
                tabWidget = self.createNewTableWidget('preview', label)        
                self.setSnapshotTable(data, tabWidget, eid)
                #sort the table by "Connection"
                tabWidget.sortByColumn(1,1)
 
                for j in range(len(data['isConnected'])):
                    if not data['isConnected'][j]:
                        disConnectedPVs.append(data['PV Name'][j])
                if len(disConnectedPVs) > 0:
                    detailedText = ""
                    for i in range(len(disConnectedPVs)):
                        detailedText += '\n' + disConnectedPVs[i]          
                    #print(detailedText)
                    msg = QMessageBox(self, windowTitle="Warning", 
text="%d PVs in the Config %s are disconnected, click Show Details ... below to see the PV list\n\n\
Click Continue... if you are satisfied, Otherwise click Ignore"%(len(disConnectedPVs),cname))
                    msg.setDetailedText(detailedText)
                else:
                    msg = QMessageBox(self, windowTitle="Good Machine Snapshot", 
                    text="Great! All PVs in the Config %s have valid data so it's a good snapshot\n\n\
 Click Ignore if you don't want to save it to the MASAR database, Otherwise Click Continue..."%cname)             
                msg.setModal(False)
                continueButton = msg.addButton("Continue...", QMessageBox.ActionRole)
                quitButton = msg.addButton(QMessageBox.Ignore)
                msg.setAttribute(Qt.WA_DeleteOnClose)
                msg.show()
                continueButton.clicked.connect(self.saveMachinePreviewAction) 
                quitButton.clicked.connect(self.createLog4InvisibleSnapshot) 
        else:
            self.saveMachineSnapshotButton.setEnabled(True)

    def getMachinePreviewData(self, configName):
        """
        This method will save current snapshot data to the MASAR database as long as users click
        the button 'Save Machine Snapshot ...'. It may generate invisible snapshots
        """
        params = {'configname': configName,
                  'servicename': 'masar'}
        
        try:
            rpcResult = self.mc.saveSnapshot(params)
        except:
            QMessageBox.warning(self,
                                "Warning",
                                "Except happened during getting machine preview.")
            return False
        if not rpcResult:
            QMessageBox.warning(self,
                                "Warning",
                                "Failed to save a snapshot")
            print("failed to save a snapshot for %s"%configName)
            return False
        eventid = rpcResult[0]
        pvnames = rpcResult[1]
        s_value = rpcResult[2]
        d_value = rpcResult[3]
        i_value = rpcResult[4]
        dbrtype = rpcResult[5]
        isConnected = rpcResult[6]
        ts = rpcResult[7]
        ts_nano = list(rpcResult[8])
        severity = list(rpcResult[9])
        status = list(rpcResult[10])
        is_array = rpcResult[11]
        raw_array_value  = rpcResult[12]

        array_value = []
        for i in range(len(severity)):
            try:
                severity[i] = self.severityDict[severity[i]]
            except:
                severity[i] = 'N/A'
            try:
                status[i] = self.alarmDict[status[i]]
            except:
                status[i] = 'N/A'

            if dbrtype[i] in self.epicsLong:
                array_value.append(raw_array_value[i][2])
            elif dbrtype[i] in self.epicsDouble:
                array_value.append(raw_array_value[i][1])
            elif dbrtype[i] in self.epicsString:
                # string value
                array_value.append(raw_array_value[i][0])
            elif dbrtype[i] in self.epicsNoAccess:
                # when the value is no_access, use the double value no matter what it is
                array_value.append(raw_array_value[i][1])
        
        data = odict()
        data['PV Name'] = pvnames
        data['Status'] = status
        data['Severity'] = severity
        data['Time stamp'] = ts
        data['Time stamp (nano)'] = ts_nano
        data['DBR'] = dbrtype
        data['S_value'] = s_value
        data['I_value'] = i_value
        data['D_value'] = d_value
        data['isConnected'] = isConnected
        data['isArray'] = is_array
        data['arrayValue'] = array_value

        return (eventid, data)

    def createLog4InvisibleSnapshot(self):
        self.saveMachineSnapshotButton.setEnabled(True)
        logText="saved an invisible snapshot %s using Conifg %s"%(self.previewId,self.previewConfName)
        #self.createLogEntry(logText,logbookName='Controls Commissoning')
    
    def saveMachinePreviewAction(self):
        #if self.previewId == None or self.previewConfName == None:
        if self.previewConfName == None:
            QMessageBox.warning(self, "Warning",
                                'No preview to save. Please click "Preview Machine" first')
            self.saveMachineSnapshotButton.setEnabled(True)
            return
        elif self.isPreviewSaved:
            QMessageBox.warning(self, "Warning",
"Preview (id: %s) for config (%s) has already been saved" %(self.previewId, self.previewConfName))
            self.saveMachineSnapshotButton.setEnabled(True)
            return

        comment = self.__getComment()
        if comment and isinstance(comment, tuple):
            if comment[0] and comment[1]: 
                commentDetail = ''
                if pyOlogExisting: 
                    commentDetail = self.__getCommentDetail()
                if self.saveMachinePreviewData(self.previewId, self.previewConfName, comment):
                    if commentDetail: 
                        logText="Succeed to save a snapshot #%s to MASAR database using Conifg %s  \
with description: %s.\nComment: %s"%(self.previewId,self.previewConfName,comment[1],commentDetail)
                    else:
                        logText="Succeed to save a snapshot #%s to MASAR database using Conifg %s  \
with description: %s"%(self.previewId, self.previewConfName, comment[1])
                    self.createLogEntry(logText)
                    self.saveMachineSnapshotButton.setEnabled(True)
                else:
                    self.createLog4InvisibleSnapshot()
                    self.saveMachineSnapshotButton.setEnabled(True)
                    return
                    
            else:#if comment[0] and comment[1]: 
                QMessageBox.warning(self,"Warning","Either user name or comment is empty.")
                self.createLog4InvisibleSnapshot()
                self.saveMachineSnapshotButton.setEnabled(True)
                return
        else:#if comment and isinstance(comment, tuple):
            self.createLog4InvisibleSnapshot()
            self.saveMachineSnapshotButton.setEnabled(True)
            return
        
        self.isPreviewSaved = True

    def __getComment(self):
        cdlg = commentdlg.CommentDlg()
        cdlg.exec_()
        if cdlg.isAccepted:
            return (cdlg.result())
        else:
            return None

    def __getCommentDetail(self):
        import commentdetail
        cdlg = commentdetail.CommentDetail()
        cdlg.exec_()
        if cdlg.isAccepted:
            return (cdlg.result())
        else:
            return None

    def saveMachinePreviewData(self, eventid, confname, comment):
        if not eventid:
            QMessageBox.warning(self,
                        "Warning",
                        "Unknown event.")
            return False

        params = {'eventid':    str(eventid),
                  'configname': str(confname),
                  'user':       str(comment[0]),
                  'desc':       str(comment[1])}
        try:
            result = self.mc.updateSnapshotEvent(params)
        except:
            QMessageBox.warning(self,
                                "Warning",
                                "Except happened during update snapshot event.")
            return False
        if result:
            QMessageBox.information(self,"Successful", 
                        " Succeed to save a snapshot %s to MASAR database using Conifg %s\n\n \
You may re-select the Config (click 'Select Snapshots(s)') to verify this new saved snapshot"\
                                    %(self.previewId,self.previewConfName))
            return True
        else:
            QMessageBox.information(self, "Failures", "Failed to save preview.")
            return False
#********* End of Save machine snapshot ********************************************************* 


#********* Start of machine snapshot retrieve *****************************************************  
    def eventFilterChanged(self):
        """           
        see ui_masar.py(.ui) 
        QtCore.QObject.connect(self.eventFilterLineEdit, 
                    QtCore.SIGNAL(_fromUtf8("textChanged(QString)")), masar.eventFilterChanged)
        """
        self.eventConfigFilter = str(self.eventFilterLineEdit.text())
        self.fetchEventAction()
       
    def authorTextChanged(self):
        """
        see ui_masar.py(.ui) 
        QtCore.QObject.connect(self.authorTextEdit, 
                    QtCore.SIGNAL(_fromUtf8("textChanged(QString)")), masar.authorTextChanged) 
        """
        self.authorText = str(self.authorTextEdit.text())
        self.fetchEventAction()
        
    def useTimeRange(self, state):
        """
        see ui_masar.py(.ui)
        QtCore.QObject.connect(self.timeRangeCheckBox, 
                    QtCore.SIGNAL(_fromUtf8("stateChanged(int)")), masar.useTimeRange)
        """
        if state == Qt.Checked:
            self.eventStartDateTime.setEnabled(True)
            self.eventEndDateTime.setEnabled(True)
        else:
            self.eventStartDateTime.setEnabled(False)
            self.eventEndDateTime.setEnabled(False) 
    
    def fetchEventAction(self):
        """
        click the button 'Select Snapshot(s)' or 'Display Golden Snapshot'
        eventOrder is a list of numbers (not strings)
        see ui_masar.py(.ui)
        QtCore.QObject.connect(self.fetchEventButton,  
                    QtCore.SIGNAL(_fromUtf8("clicked(void)")), masar.fetchEventAction)
                    
         also in setConfigTable(): 
         QObject.connect(self.configTableWidget, 
                            SIGNAL(_fromUtf8("itemSelectionChanged()")),self.fetchEventAction)
        """
        selectedConfigs = self.configTableWidget.selectionModel().selectedRows()
        if len(selectedConfigs) <= 0:
            #QMessageBox.warning(self,
                            #"Warning",
                            #"Please select at least one Config listed in the Config table above.")
            return
                
        configIds=[]
        configNames = []
        for idx in selectedConfigs: 
            #configIds.append(str(self.configTableWidget.item(idx.row(), 4).text()))
            configIds.append(str(self.configTableWidget.item(idx.row(), 1).text()))
            configNames.append(str(self.configTableWidget.item(idx.row(), 0).text()))
        
        #print(configIds)
        data = self.retrieveEventData(configids=configIds, confignames=configNames)
        reorderedData = odict([('Config Name', []), ('SID', []), ('Description', []), \
                               ('Time stamp', []), ('Author', [])]) 
        if not data: 
            QMessageBox.warning(self, "warning","Can't retrieve event list")
            return
        #if not data['SID']:
            #return
        #print('\nsetEventTable')
        #print(data['SID'])
        eventOrder = [] # a list of numbers (not strings)
        #get golden SID first
        goldenDataFile = self.goldenDataFilePath + "goldenSnapshotOf" + str(configNames[0]) + ".data"
        if os.path.isfile(goldenDataFile):
            fd = open(goldenDataFile, 'r')
            lines = fd.readlines()
            fd.close() 
            for line in lines:
                eventOrder.append(int(line.split('#')[0].strip()))
            eventOrder.reverse()        
        if eventOrder != []: #add prefix G* to golden snapshot desc
            #print(eventOrder)
            for i in range(len(eventOrder)):
                desc = " [G%i] "%(i+1)
                desc += data['Description'][list(data['SID']).index(eventOrder[i])]
                data['Description'][list(data['SID']).index(eventOrder[i])] = desc
                #print(desc)
        #get customzied SID from masar.cfg        
        eventInConf = []
        eventInConfStr = ''
        try:
            for cname in configNames:
                eventInConfStr += str(masarConfigDict["Order"][str(cname).lower()]) + " "
                eventInConf = [int(evt) for evt in eventInConfStr.split() if evt.isdigit()]
        except:
            pass        
        #print(str(eventOrder) + "in fetchEventAction")
        eventOrder += eventInConf
        eventOrderSet = set(eventOrder)   
        #print(str(eventOrderSet) + "set in fetchEventAction")
        #print(eventOrderSet.issubset(set(data['SID'])))
        #print(set(data['SID']))
        if eventOrderSet and eventOrderSet.issubset(set(data['SID'])):
            #print("eventOrder is a subset") 
            for evt in eventOrder:
                reorderedData['Config Name'].append(data['Config Name'][list(data['SID']).index(evt)])
                reorderedData['SID'].append(evt)
                reorderedData['Description'].append(data['Description'][list(data['SID']).index(evt)])
                reorderedData['Time stamp'].append(data['Time stamp'][list(data['SID']).index(evt)])
                reorderedData['Author'].append(data['Author'][list(data['SID']).index(evt)])
            evtL = list(set(data['SID']).difference(eventOrderSet))  
            evtL.sort(reverse=True)
            #print(evtL)
            for evt in evtL:
                reorderedData['Config Name'].append(data['Config Name'][list(data['SID']).index(evt)])
                reorderedData['SID'].append(evt)
                reorderedData['Description'].append(data['Description'][list(data['SID']).index(evt)])
                reorderedData['Time stamp'].append(data['Time stamp'][list(data['SID']).index(evt)])
                reorderedData['Author'].append(data['Author'][list(data['SID']).index(evt)])         
            data =  reorderedData  
            self.eventTableWidget.setSortingEnabled(False) 
            self.setEventTable(data)
            self.eventTableWidget.sortByColumn(0,1)
            self.eventTableWidget.setSortingEnabled(True) 
        else:
            #print("no customized event order")    
            self.eventTableWidget.setSortingEnabled(False) 
            self.setEventTable(data)
            self.eventTableWidget.setSortingEnabled(True)
            self.eventTableWidget.sortByColumn(3,1)
        self.eventTableWidget.resizeColumnsToContents()
            

    def retrieveEventData(self,configids=None,confignames=None):
        """
        only called by fetchEventAction(): EventData here doesn't inlcude epics PV data, it only gives event header
        information for given / selected Config -- how many events/snapshots have been taken 
        retrieveMasarData(eventId) returns PV data
        """
        start = None
        end = None
        if self.timeRangeCheckBox.isChecked():
            start = self.eventStartDateTime.dateTime().toPyDateTime() + self.UTC_OFFSET_TIMEDELTA
            end = self.eventEndDateTime.dateTime().toPyDateTime() + self.UTC_OFFSET_TIMEDELTA
            if start > end:
                QMessageBox.warning(self,
                            "Warning",
                            "Please select a correct time range.")
                return

        event_ids = []
        event_ts = []
        event_desc = []
        c_names = []
        event_author = []
        #self.e2cDict.clear()#don't clear this global dict.

        if configids:
            for i in range(len(configids)):
                cid = configids[i]
                params = {'configid': cid,
                          "comment": self.eventConfigFilter,
                          "user": self.authorText}
                if self.timeRangeCheckBox.isChecked():
                    params['start'] = str(start)
                    params['end'] = str(end)
                try:
                    rpcResult = self.mc.retrieveServiceEvents(params)
                except:
                    QMessageBox.warning(self,
                                "Warning",
                                "Except happened during retrieving events.")
                    return False
                if not rpcResult:
                    return False
                eids = rpcResult[0]
                usertag = rpcResult[1]
                utctimes = rpcResult[2]
                author = rpcResult[3]

                event_ids = event_ids[:] + (list(eids))[:]
                event_desc = event_desc[:] + (list(usertag))[:]
                event_author = event_author[:] + (list(author))[:]
                for j in range(len(eids)):
                    self.e2cDict[str(eids[j])] = [cid, usertag[j],confignames[i]]
                for ut in utctimes:
                    c_names.append(confignames[i])
                    ts = str(datetime.datetime.fromtimestamp(time.mktime(time.strptime(
                            ut, self.time_format))) - self.UTC_OFFSET_TIMEDELTA)
                    event_ts.append(ts)
        else:
            return False
                    
        data = odict()
        data['Config Name'] = c_names
        data['SID'] = event_ids        
        data['Description'] = event_desc
        data['Time stamp'] = event_ts
        data['Author'] = event_author
        return data
               
    def setEventTable(self, data):
        """
        interesting / potential problem: double click on any event will call retrieveSnapshot()
        many times, which makes retrieving snapshot slower. Clicking the fetchSnapshotButton 
        only call retrieveSnapshot() once, which instantly retrieves snapshot(s) 
        """
        self.setTable(data, self.eventTableWidget)
        #self.eventTableWidget.sortByColumn(3)
        #tableId = 1
        #the following have the same function
        self.eventTableWidget.doubleClicked.connect(self.retrieveSnapshot)
        #QApplication.processEvents(QEventLoop.AllEvents)
        #self.eventTableWidget.cellDoubleClicked.connect(self.retrieveSnapshot)
        #self.eventTableWidget.itemDoubleClicked.connect(self.retrieveSnapshot)
        #QObject.connect(self.eventTableWidget, 
                            #SIGNAL(_fromUtf8("cellDoubleClicked (int,int)")),self.retrieveSnapshot)    

    def snapshotIdChanged(self):
        """
        see ui_masar.py(.ui)
        QtCore.QObject.connect(self.snapshotIdLineEdit, 
                QtCore.SIGNAL(_fromUtf8("textChanged(QString)")), masar.snapshotIdChanged)
        """
        snapshotID = self.snapshotIdLineEdit.text()
        #print(snapshotID)
        
    def retrieveSnapshotById(self, eventId=" "):
        """
        see ui_masar.py(.ui)
        QtCore.QObject.connect(self.searchSnapshotButton, 
                QtCore.SIGNAL(_fromUtf8("clicked()")), masar.retrieveSnapshotById)
        """
        #print("test")
        if eventId == " ": 
            eventId = str(self.snapshotIdLineEdit.text())
        if not eventId.isdigit():
            QMessageBox.warning(self, 'Error', 'You have to enter one integer number and only one \
in the left box. Try again if you want')
            return
        
        #data = self.retrieveMasarData(eventid=eventId) 
        #if data == None or not isinstance(data, odict):
            #QMessageBox.warning(self, "Error", "Can't get snapshot data for eventId:%s.\
#You may have typed one invalid ID"%eventId)
            #return
        
        eventIds = []
        eventIds.append(eventId)
        try:
            params = {'eventid': eventId}
            #retrieveService(Configs/Events) returns a list of tuples
            (configID, configName, configDesc, date, version, status) = self.mc.retrieveServiceConfigs(params)
            (snapshotID, snapshotDesc, ts, author) = self.mc.retrieveServiceEvents(params)#snapshotDesc is tuple
            self.e2cDict[eventId] = [configID[0], snapshotDesc[0],configName[0]]#this is required for searchPV()
            eventNames = []
            eventTs = []
            for i in range(len(configName)):
                eventNames.append(configName[i])
                eventTs.append(ts[i])       
        except:
            traceback.print_exc()
            QMessageBox.warning(self, "Error", "Can't get Config information related to eventId:%s.\
You may have typed one invalid ID"%eventId)
            return
            
        self.setSnapshotTabWindow(eventNames, eventTs, eventIds)
        #highlight / select the Config and Event 
        self.findConfigAndEvent(configName[0], eventId)
    
    def findConfigAndEvent(self, configName, eventId):
        configTable = self.configTableWidget
        for i in range(configTable.rowCount()):
            if configName == configTable.item(i, 0).text():
                configTable.setCurrentCell(i, 0)
                break
                #time.sleep(1.0) 
        eventTable = self.eventTableWidget
        for j in range(eventTable.rowCount()):
            if eventId == eventTable.item(j, 1).text():
                eventTable.setCurrentCell(j, 0)
                break
                
    def retrieveSnapshot(self):
        """
        Click the button 'Display Snapshot(s)'
        self.retrieveSnapshot() --> self.setSnapshotTabWindow() --> self.retrieveMasarData() -->
            --> self.mc.retrieveSnapshot
        
        see ui_masar.py(.ui)
        QtCore.QObject.connect(self.fetchSnapshotButton, 
                                QtCore.SIGNAL(_fromUtf8("clicked(void)")), masar.retrieveSnapshot)
         
        also in setEventTable():                       
        self.eventTableWidget.doubleClicked.connect(self.retrieveSnapshot)
        """
        selectedItems = self.eventTableWidget.selectionModel().selectedRows()
        if len(selectedItems) <= 0:
            QMessageBox.warning(self,
                            "Warning",
                            "Please select at least one Snapshot in the Snapshot table above.")
            return

        eventTs=[]
        eventNames=[]
        eventIds = []
        for idx in selectedItems: 
            eventNames.append(str(self.eventTableWidget.item(idx.row(), 0).text()))
            eventTs.append(str(self.eventTableWidget.item(idx.row(), 3).text()))
            eventIds.append(str(self.eventTableWidget.item(idx.row(), 1).text()))
            
        self.timeAtRetrieveSnapshot = time.time()
        loopTime = self.timeAtRetrieveSnapshot - self.timeAtSetSnapshotTabWindow
        if loopTime > 1.0: #fix the problem: double-click triggers multiple-retrieve-requests     
            #print(datetime.datetime.now())
            self.setSnapshotTabWindow(eventNames, eventTs, eventIds)
        #this doesn't work well: wait for seconds, then get the Live Machine data
        #QThread.sleep(2)
        #Sleep(0.3)
        #self.getLiveMachineAction()   
        
    def setSnapshotTabWindow(self, eventNames, eventTs, eventIds):
        """
        ideally, this method only sets snapshot table. 
        retrieveMasarData() should be in retrieveSnapshot().
        SIGNAL(_fromUtf8("cellDoubleClicked (int,int)")),self.__showArrayData):
            __showArrayData() is called once, which is correct
        """
        tableWidget = None
        isNew = True
        
        #print(eventIds)
        for i in range(len(eventIds)):
            data = self.retrieveMasarData(eventid=eventIds[i])
            #print(len(data['PV Name']))
            #if None == data:
            if data == None or not isinstance(data, odict):
                QMessageBox.warning(self, "Warning", 
                                    "Can't get snapshot data for eventId:%s"%eventIds[i])
            
            ts = eventTs[i].split('.')[0] 
            label = QString.fromUtf8((eventNames[i]+': ' +eventIds[i]+": "+ ts))            
            tableWidget = self.createNewTableWidget(eventIds[i], label)        
            self.setSnapshotTable(data, tableWidget, eventIds[i])
            
            self.pv4cDict[str(eventIds[i])] = data['PV Name']
            self.data4eid[str(eventIds[i])] = data         
            tableWidget.setStatusTip("Snapshot data of " + eventNames[i] + " saved at " + ts)
            tableWidget.setToolTip("Sort the table by column \n Ctrl + C to copy \n \
Double click to view waveform data")
            self.resizeSplitter(1)
                          
        #self.snapshotTabWidget.setCurrentIndex(1)
        #print("total tabs:%d"%self.snapshotTabWidget.count())
        self.snapshotTabWidget.setCurrentIndex(self.snapshotTabWidget.count())
        self.snapshotTabWidget.setCurrentWidget(tableWidget)
        self.timeAtSetSnapshotTabWindow = time.time()

    def __showArrayData(self, row, column):
        #if column != 5 and column != 6: # display the array value only
        curWidget = self.snapshotTabWidget.currentWidget()
        if not isinstance(curWidget, QTableWidget):
            QMessageBox.warning(self, 'Warning', 'No snapshot is selected yet.')
            return
        
        pvname = str(curWidget.item(row, 0).text())
        eid = self.__find_key(self.tabWindowDict, curWidget)
        eid_ = eid
        #print(eid)
        if eid == 'comment':
            QMessageBox.warning(self, 'Warning', 'It is comment panel.')
            return
        #in non-compare tab, saved value / live value  is in column 3 / 4
        if eid != "compare": 
            if column != 3 and column != 4: 
                #print(column)
                return       
        if eid == "compare":
            if column < 1 or column > 1 + len(self.eventIds):
                #print("compare: %d"%column)
                return
        
        if eid == 'preview':
            eid_ = self.previewId
        #print("pv / eid_: %s / %s"%(pvname, eid_))
        if eid == "compare":
            if column == 1 + len(self.eventIds):#live value column: use the Ref. snapshot
                eid_ = str(self.eventIds[0])+'_compare'
            else:
                eid_ = str(self.eventIds[column-1])+'_compare'
            #print("pv / eid_: %s / %s"%(pvname, eid_))
        try:
            arraySaved = self.arrayData[pvname+'_'+str(eid_)]
        except:
            QMessageBox.warning(self, 'Warning', 'No saved array data for the PV %s'%pvname)
            return
        #print("eid / eid_: %s / %s"%(eid, eid_))
        if eid != 'preview':
            try:
                arrayLive = self.arrayData[pvname+"_"+str(eid)+'_live']
                arrardlg = ShowArrayValueDlg(pvname, arraySaved, arrayLive)
            except:
                arrardlg = ShowArrayValueDlg(pvname, arraySaved)
        else:
            arrardlg = ShowArrayValueDlg(pvname, arraySaved)
        arrardlg.exec_()
        #arrardlg.show()
        #arrardlg.raise_()
        #arrardlg.activateWindow()
        
    def __find_key(self, dic, val):
        """return the key of dictionary dic given the value"""
        return [k for k, v in dic.iteritems() if v == val][0]
    
    def retrieveMasarData(self, eventid=None):
        """
        retrieve saved snapshot data including time stamp, alarm, etc. from MASAR database
        called by setSnapshotTabWindow() and compareSnapshots() 
        """
        data = odict()

        params = {'eventid': eventid}
        
        try:
            rpcResult = self.mc.retrieveSnapshot(params)
        except:
            #QMessageBox.warning(self, "Warning",
                                #"Except happened during retrieving snapshot data.")
            #return False
            return rpcResult
        if not rpcResult:
            return False
        #print("retrieveMasarData() is called")
        pvnames = rpcResult[0]
        s_value = rpcResult[1]
        d_value = rpcResult[2]
        i_value = rpcResult[3]
        dbrtype = rpcResult[4]
        isConnected = rpcResult[5]
        ts = rpcResult[6]
        ts_nano = rpcResult[7]
        severity = list(rpcResult[8])
        status = list(rpcResult[9])
        is_array = rpcResult[10]
        raw_array_value  = rpcResult[11]
        
        array_value = []
        for i in range(len(severity)):
            try:
                severity[i] = self.severityDict[severity[i]]
            except:
                severity[i] = 'N/A'
            try:
                status[i] = self.alarmDict[status[i]]
            except:
                status[i] = 'N/A'

            if dbrtype[i] in self.epicsLong:
                array_value.append(raw_array_value[i][2])
            elif dbrtype[i] in self.epicsDouble:
                array_value.append(raw_array_value[i][1])
            elif dbrtype[i] in self.epicsString:
                # string value
                array_value.append(raw_array_value[i][0])
            elif dbrtype[i] in self.epicsNoAccess:
                # when the value is no_access, use the double value no matter what it is
                array_value.append(raw_array_value[i][1])

        data['PV Name'] = pvnames
        data['Status'] = status
        data['Severity'] = severity
        data['Time stamp'] = ts
        data['Time stamp (nano)'] = ts_nano
        data['DBR'] = dbrtype
        data['S_value'] = s_value
        data['I_value'] = i_value
        data['D_value'] = d_value
        data['isConnected'] = isConnected
        data['isArray'] = is_array
        data['arrayValue'] = array_value
        
        return data
                
    def setSnapshotTable(self, data, table, eventid):
        """
        called by setSnapshotTabWindow(), saveMachineSnapshot()(preview table), and searchPV() 
        This table is different from compareSnapshotsTable, see setCompareSnapshotsTable()
        """
        if data:
            length = len(data.values()[0])
        else:
            print ('data is empty, exit.')
            return
        
        for i in range(1, len(data.values())):
            if length != len(data.values()[i]):
                QMessageBox.warning(self,
                                    "Warning",
                                    "Data length are not consistent.")
                return

        if isinstance(data, odict) and isinstance(table, QTableWidget):
            table.setSortingEnabled(False)
            table.clear()
        
            nrows = len(data.values()[0])
            keys = ['PV Name', 'Saved Connection', 'Not Restore','Saved Value','Live Value','Diff', 
                    'Saved Timestamp', 'Saved Status','Saved Severity',
                    'Live Connection', 'Live Timestamp', 'Live Status', 'Live Severity']
            #keys = ['PV Name', 'Description', 'Not Restore', 'Saved Value', 'Live Value', 'Diff', 
                    #'Saved Connection', 'Saved Timestamp', 'Saved Status','Saved Severity',
                    #'Live Connection', 'Live Timestamp', 'Live Status', 'Live Severity']
            #ncols = len(data) - 3
            ncols = len(keys)
            table.setRowCount(nrows)
            table.setColumnCount(ncols)
            table.setHorizontalHeaderLabels(keys)

            pvnames = data['PV Name']
            status = data['Status']
            severity = data['Severity']
            ts = data['Time stamp']
            ts_nano = data['Time stamp (nano)']
            dbrtype = data['DBR']
            s_value = data['S_value']
            i_value = data['I_value']
            d_value = data['D_value']
            isConnected = data['isConnected']
            is_array = data['isArray'] 
            array_value = data['arrayValue']
            
            #pvs = [pvnames[m]+'.DESC' for m in range(len(pvnames))]
            #v3Results = cav3.caget(pvs, timeout=2, throw=False)
            #for n in range(len(pvs)):
                #print("%s    %s"%(pvs[n], v3Results[n]))
            
            for i in range(nrows):
                #item = table.item(i, 8)
                item = table.item(i, 2)
                if item:
                    item.setCheckState(False)
                else:
                    item = QTableWidgetItem()
                    item.setFlags(Qt.ItemIsEnabled|Qt.ItemIsUserCheckable)
                    #table.setItem(i, 8, item)
                    table.setItem(i, 2, item)
                    item.setCheckState(False)

                if pvnames[i]:
                    self.__setTableItem(table, i, 0, pvnames[i])
                if status[i]:
                    #self.__setTableItem(table, i, 1, str(status[i]))
                    self.__setTableItem(table, i, 7, str(status[i]))
                if severity[i]:
                    #self.__setTableItem(table, i, 2, str(severity[i]))
                    self.__setTableItem(table, i, 8, str(severity[i]))
                if ts[i]:
                    dt = str(datetime.datetime.fromtimestamp(ts[i]+ts_nano[i]*1.0e-9))
                    #self.__setTableItem(table, i, 3, dt)
                    self.__setTableItem(table, i, 6, dt)
                        
                if is_array[i]:
                    self.__setTableItem(table, i, 3, self.__arrayTextFormat(array_value[i]))
                    #self.__setTableItem(table, i, 5, self.__arrayTextFormat(array_value[i]))
                    self.arrayData[pvnames[i]+'_'+str(eventid)] = array_value[i]
                else:
                    if dbrtype[i] in self.epicsDouble:
                        #self.__setTableItem(table, i, 5, str(d_value[i]))
                        self.__setTableItem(table, i, 3, str(d_value[i]))
                    elif dbrtype[i] in self.epicsLong:
                        #self.__setTableItem(table, i, 5, str(i_value[i]))
                        self.__setTableItem(table, i, 3, str(i_value[i]))
                    elif dbrtype[i] in self.epicsString:
                        #self.__setTableItem(table, i, 5, str(s_value[i]))
                        self.__setTableItem(table, i, 3, str(s_value[i]))
                    elif dbrtype[i] in self.epicsNoAccess:
                        # channel are not connected.
                        pass
                    else:
                        print('invalid dbr type (code = %s)'%(dbrtype[i]))
                
                if isConnected[i]:
                    #self.__setTableItem(table, i, 4, str(bool(isConnected[i])))
                    self.__setTableItem(table, i, 1, "Connected")
                    #self.__setTableItem(table, i, 1, "Restorable")
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                else:
                    #self.__setTableItem(table, i, 4, 'False')
                    self.__setTableItem(table, i, 1, 'Disconnected')
                    item.setCheckState(True)
                    item.setSelected(True)
                    # disable user checkable function
                    item.setFlags(item.flags() ^ Qt.ItemIsUserCheckable)
                    for item_idx in range(9):
                        itemtmp = table.item(i, item_idx)
                        if not itemtmp:
                            itemtmp = QTableWidgetItem()
                            table.setItem(i, item_idx, itemtmp)
                        itemtmp.setBackground(self.brushbadpv)
                
                #if v3Results[i]:
                    #self.__setTableItem(table, i, 1, str(v3Results[i]))

            table.setSortingEnabled(True)
            #be careful of this sorting action 
            #sort by "Connection"  
            table.sortItems(1,1)
            table.resizeColumnsToContents()
        else:
            raise "Error occurred in setSnapshotTable(self, data, table, eventid)"

    def __setTableItem(self, table, row, col, text):
        item = table.item(row, col)
        if item:
            item.setText(text)
        else:
            newitem = QTableWidgetItem(text)
            newitem.setFlags(Qt.ItemIsEnabled|Qt.ItemIsSelectable)
            table.setItem(row, col, newitem)

    def __arrayTextFormat(self, arrayvalue):
        """
        display max 8 characters in a table cell
        """
        array_text = str(arrayvalue)

        if len(str(array_text)) > 8:
            array_text = str(array_text)[:8]+' ..., ...)'

        return array_text
#********* End of machine snapshot retrieve *******************************************************


#************************** Start of config snapShotTab *******************************************  
    def closeTab(self, index):
        """
        snapshotTab is closable, movable
        See ui_masar.py(.ui):
        QtCore.QObject.connect(self.snapshotTabWidget, 
                    QtCore.SIGNAL(_fromUtf8("tabCloseRequested(int)")), masar.closeTab)
        """
        #index = self.snapshotTabWidget.currentIndex()
        if index != 0:
            self.snapshotTabWidget.removeTab(index)
            #print("the selected tab is closed")
        else:
            QMessageBox.warning(self, "Waring", 
                                "Please don't close this page since it has all instructions")

    def configTab(self):
        """
        Highligt the tabBar of the active/selected snapshotTab
        and highlight snapshot related Config / Event  
        See ui_masar.py(.ui):
        QtCore.QObject.connect(self.snapshotTabWidget, 
                    QtCore.SIGNAL(_fromUtf8("currentChanged(int)")), masar.configTab)
        """
        # this won't work: 
        ##AttributeError: 'builtin_function_or_method' object has no attribute 'setTabTextColor'
        #self.snapshotTabWidget.tabBar.setTabTextColor(0, Qt.blue)
        #print("start of configTab: %s"%datetime.datetime.now())
        bar = self.snapshotTabWidget.tabBar()
        #bar.setTabTextColor(0, Qt.blue) // for quick test
        totalTabs = self.snapshotTabWidget.count()
        curIndex = self.snapshotTabWidget.currentIndex()
        for i in range(totalTabs):
            if i == curIndex: 
                bar.setTabTextColor(i, Qt.blue)
            else:
                bar.setTabTextColor(i, Qt.gray)
        
        #automatically update Config & Event table:         
        try:
            #(data, pvlist, eid, eventIds, config) = self.getInfoFromTableWidget()
            #print("try of configTab: %s"%datetime.datetime.now())
            curWidget = self.snapshotTabWidget.currentWidget()
            if not isinstance(curWidget, QTableWidget):
                self.fetchConfigAction() # update / un-highlight Configtable
                self.eventTableWidget.clearContents()
                return
            eid = self.__find_key(self.tabWindowDict, curWidget)
            if eid == 'comment' or eid == 'compare':
                self.fetchConfigAction() # update / un-highlight Configtable
                self.eventTableWidget.clear()
                return
            if eid == 'preview':
                eid = self.previewId
            if eid == 'filter':
                eid = self.origID
            #params = {'eventid': eid}
            #(configID, configName, configDesc, date, version, status) = self.mc.retrieveServiceConfigs(params)
            [cid, desc, configName] = self.e2cDict[str(eid)]
            #print("get configName configTab: %s"%datetime.datetime.now())
            #print((configName, eid))
            self.findConfigAndEvent(configName, str(eid))
            #print("end of configTab: %s"%datetime.datetime.now())
        except:
            traceback.print_exc()
        
        #print("total tabs / current tab index: %s / %s" %(totalTabs, curIndex))
#************************** End of config snapShotTab *********************************************   
 
#************************ Start of machine restore: simple put or ramping *************************     
    def ignore4RestoreMachine(self):
        self.restoreMachineButton.setEnabled(True)
        self.rampingMachineButton.setEnabled(True)
        return
    
    def getRestoreInfo(self):
        curWidget = self.snapshotTabWidget.currentWidget()
        if not isinstance(curWidget, QTableWidget):
            QMessageBox.warning(self, 'Warning', 
                        'No snapshot is selected yet. Please refer Welcome to MASAR for help')
            self.restoreMachineButton.setEnabled(True)  
            self.rampingMachineButton.setEnabled(True)
            return
        
        eid = self.__find_key(self.tabWindowDict, curWidget)
        if eid == 'comment' or eid == 'preview' or eid == 'compare':
            QMessageBox.warning(self, 'Warning', 
                        'No restore, %s tab is selected. Please select other Non-%s Tab'%(eid,eid))
            self.restoreMachineButton.setEnabled(True)  
            self.rampingMachineButton.setEnabled(True)
            return
        if eid == 'filter':
            eid4Log = self.origID + '(filtered with pattern %s)'%self.currentPvFilter
        else:
            eid4Log = eid                      
 
        if not self.getAuthentication():
            self.restoreMachineButton.setEnabled(True)  
            self.rampingMachineButton.setEnabled(True)
            return
        
        selectedNoRestorePv = {}
        #noRestorePvList = []
        noRestorePvStr = ''
        cname = self.e2cDict[str(eid)][2]
        try:
            noRestorePvStr = masarConfigDict["NoRestore"][str(cname).lower()]
            #noRestorePvList = [str(pv) for pv in noRestorePvStr.split()]
        except:
            pass  
        #print(noRestorePvStr)

        # get table rows
        rowCount = curWidget.rowCount()
        #Qt.Unchecked           0    The item is unchecked.
        #Qt.PartiallyChecked    1    The item is partially checked. 
        #                            Items in hierarchical models may be partially checked if some, 
        #                            but not all, of their children are checked.
        #Qt.Checked             2    The item is checked.
        for row in range(rowCount):
            #selectedNoRestorePv[str(curWidget.item(row, 0).text())] =
                                                # bool(curWidget.item(row, 8).checkState())
            if str(curWidget.item(row, 0).text()) in noRestorePvStr:
                #print("    %s is not restored"%str(curWidget.item(row, 0).text()))
                curWidget.item(row, 2).setCheckState(2)
                
            selectedNoRestorePv[str(curWidget.item(row, 0).text())]= \
                                                bool(curWidget.item(row, 2).checkState())
        pvlist = list(self.pv4cDict[str(eid)])
        data = self.data4eid[str(eid)]
        s_val = data['S_value']
        d_val = data['D_value']
        i_val = data['I_value']
        dbrtype = data['DBR']
        is_array = data['isArray']
        # is_connected = data['isConnected']
        # data['PV Name']
        array_value = data['arrayValue']
         
        r_pvlist = [] # restore all pv value in this list
        r_data = []   # value to be restored.
        r_dbrtype = []
        r_isArray = [] 
        no_restorepvs = []  # either 'Not Restore' is checked or the PV is disconnected  
        ignoreall = False # Ignore all pv those do not have any value.
        for index in range(len(pvlist)):
            try:
                # pv is unchecked, which means restore this pv
                if not selectedNoRestorePv[pvlist[index]]:
                    r_pvlist.append(pvlist[index])
                    r_dbrtype.append(dbrtype[index])
                    r_isArray.append(is_array[index])
                    if is_array[index]:
                        r_data.append(array_value[index])
                    elif dbrtype[index] in self.epicsDouble:
                        r_data.append(d_val[index])
                    elif dbrtype[index] in self.epicsLong:
                        r_data.append(i_val[index])
                    elif dbrtype[index] in self.epicsString:
                        r_data.append(s_val[index])
                    elif dbrtype[index] in self.epicsNoAccess:
                        if not ignoreall:
                            reply = QMessageBox.warning(self, 'Warning', 
'Cannot restore pv: %s\nValue is invalid.\nDo you want to ignore it and continue?'%(pvlist[index]),
                QMessageBox.Yes | QMessageBox.YesToAll | QMessageBox.Cancel, QMessageBox.Cancel)
                            if reply == QMessageBox.Yes:
                                no_restorepvs.append(pvlist[index])
                            elif reply == QMessageBox.YesToAll:
                                no_restorepvs.append(pvlist[index])
                                ignoreall = True
                            elif reply == QMessageBox.Cancel:
                                self.restoreMachineButton.setEnabled(True)
                                self.rampingMachineButton.setEnabled(True)
                                return
                        else:
                            no_restorepvs.append(pvlist[index])
                else:
                    no_restorepvs.append(pvlist[index])
            except:
                print (type(pvlist[index]), pvlist[index])
                QMessageBox.warning(self, 'Warning', 'PV name (%s) is invalid.'%(pvlist[index]))
                self.restoreMachineButton.setEnabled(True)
                self.rampingMachineButton.setEnabled(True)
                return
    
        if len(no_restorepvs) == rowCount:
            QMessageBox.warning(self, 'Warning', 'All pvs are checked, and not restoring.')
            self.restoreMachineButton.setEnabled(True)
            self.rampingMachineButton.setEnabled(True)
            return
   
        #print("%s: starting to get live machine data"%datetime.datetime.now())
        liveData = self.getLiveMachineData(r_pvlist)
        if not liveData:
            self.restoreMachineButton.setEnabled(True)  
            self.rampingMachineButton.setEnabled(True)
            return
        disConnectedPVs = liveData[8]#disconnected PV belongs to no_restorepvs
        #print("%s: got live machine data"%datetime.datetime.now())     
        for i in range(len(disConnectedPVs)):
            if disConnectedPVs[i] not in no_restorepvs:
                no_restorepvs.append(disConnectedPVs[i])
        #print(no_restorepvs)
        str_no_restore = "\n"
        if len(no_restorepvs) > 0: 
            for no_restorepv in no_restorepvs:
                str_no_restore += ' - %s' %no_restorepv + '\n'
            print("No restore for the following pvs:\n"+str_no_restore+"\nlist end (no-restore)")
                
        if ignoreall:        
            print("No restore for the following pvs:\n"+str_no_restore+"\nlist end (no-restore)")
        elif len(disConnectedPVs) > 0:#pop up this warning only when there is a disconnected PV 
        #elif len(no_restorepvs) > 0:              
            msg = QMessageBox(self, windowTitle='Warning', 
text="%d PVs will not be restored. Click Show Details... to see the disconnected / no-restore Pvs.\n\
It may take a while to restore the machine. Do you want to continue?" 
                              %len(no_restorepvs))
            msg.setModal(False)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            msg.setDetailedText(str_no_restore)
            reply = msg.exec_()
            if reply == QMessageBox.No:
                self.restoreMachineButton.setEnabled(True)
                self.rampingMachineButton.setEnabled(True)
                return
                    
        return (eid, eid4Log, r_pvlist, r_data, r_dbrtype, r_isArray, no_restorepvs, rowCount)
 
    def simplePut(self, eid, eid4Log, r_pvlist, r_data, no_restorepvs, rowCount):
        #print("one-step simple put eventID: %s %s"%(eid,eid4Log))
        bad_pvs = [] # bad pv does not mean disconnected; disconnected pv belongs to no_restorepvs
        logText = '' # bad_pvs and no_restorepvs (Not Restore + disconnected) will be logged
        try:
            final_restorepv = []
            final_restorepvval = []
            for i in range(len(r_pvlist)):
                if r_pvlist[i] not in no_restorepvs:
                    final_restorepv.append(r_pvlist[i])
                    final_restorepvval.append(r_data[i])
            if len(final_restorepv) > 0:
                results = cav3.caput(final_restorepv, final_restorepvval, wait=True, throw=False)
                for i in range(len(results)):
                    res = results[i]
                    if not res.ok:
                        # try 3 times again to set value to each pv
                        # first try wait 1 second, second try wait 2 seconds, and last try wait 3 seconds.
                        for j in range(1, 2):
                            ressub = cav3.caput(final_restorepv[i], final_restorepvval[i], 
                                                wait=True, throw=False, timeout=j)
                            if ressub.ok:
                                break
                        if not ressub.ok:
                            # record as a bad pv if it still fails
                            bad_pvs.append(res)
        except:
            QMessageBox.warning(self, 'Warning', 'Error during restoring machine.')
            self.restoreMachineButton.setEnabled(True)
            self.rampingMachineButton.setEnabled(True)
            return
        #bad_pvs == [ca_nothing(), ca_nothing() ...]
        #bad_pvs = bad_pvs + no_restorepvs
        #print(bad_pvs)
        if len(bad_pvs) > 0:#show no_restorepvs in the pop-up message only when there are bad pvs
            #message = "Failed to restore some pvs. PLease check the terminal for a full list."
            #QMessageBox.warning(self, 'Warning', message)
            output = ""
            for bad_pv in bad_pvs:
                output += "\n  "+bad_pv.name + ": "+cav3.cadef.ca_message(bad_pv.errorcode)
            for no_restorepv in no_restorepvs:
                output += "\n  "+no_restorepv + ": Disconnected or Not Restore" 

            logText = "Snapshot #%s of Config %s was restored, but failed to restore the following \
pvs which is caused by:\n"%(eid4Log,self.e2cDict[eid][2])+output+"\n"
            #print (logText)  
            
            totalNotRestoredPVs = len(bad_pvs)+len(no_restorepvs)     
            msg = QMessageBox(self, windowTitle='Warning', 
                              text="Not Very Successful: %d PVs are not restored.\
Click Show Details... to see the failure details\n\You may take a moment to review \
the restored PV values by clicking the button Compare Live Machine"
                               %totalNotRestoredPVs)
            #msg.setStandardButtons(QMessageBox.Ok)
            msg.setDetailedText(output)
            msg.setModal(False)
            continueButton = msg.addButton("Ok", QMessageBox.ActionRole)
            quitButton = msg.addButton(QMessageBox.Ignore)
            msg.setAttribute(Qt.WA_DeleteOnClose)
            msg.show()
            continueButton.clicked.connect(self.ignore4RestoreMachine) 
            quitButton.clicked.connect(self.ignore4RestoreMachine) 
            #msg.exec_()   
        else:#DO NOT show no_restorepvs in the pop-up message; put no_restorepvs in logbook
            self.restoreMachineButton.setEnabled(True)
            self.rampingMachineButton.setEnabled(True)
            QMessageBox.information(self, "Congratulation", 
                            "Bingo! Restoring machine is done. You may take a moment to \
review the restored PV values by clicking the button Compare Live Machine")
            if len(no_restorepvs) > 0:
                str_no_restore = "\n"
                for no_restorepv in no_restorepvs:
                    str_no_restore += '    %s' %no_restorepv + '\n'
                logText = "successfully restore machine with the snapshot #%s of Conifg %s.\n\
PS: these PVs are not restored because they are 'Not Restore' or temporarily disconnected:%s" \
                        %(eid4Log, self.e2cDict[eid][2], str_no_restore)                
            else:
                logText = "successfully restore machine with the snapshot #%s of Conifg %s" \
                        %(eid4Log, self.e2cDict[eid][2])
        
        self.createLogEntry(logText)
        
        dirPath = os.path.dirname(os.path.abspath(__file__))
        #keep a local log file logging restore actions    
        try:
            logFile = dirPath + '/masar.log'
            #print(logFile)
            if not os.path.isfile(logFile):
                return
            userID =  self.userID 
            fd = open(logFile,'a')
            fd.write(str(userID)+' from '+str(platform.node())+' did a restore at %s:\n'\
                     %datetime.datetime.now())
            fd.write(logText+"\n\n")
            fd.close()     
        except:
            pass
            #traceback.print_exc()  
            
        #compare readback & setpoint after restoring machine                     
        configFile = dirPath + '/configure/' + self.e2cDict[eid][2] + '.cfg'
        if not os.path.isfile(configFile):
            return
        #print("config File exists, masar will monitor setpoint v.s. readback")
        if not self.verifyWindowDict.has_key(configFile):
            verifyWin = VerifySetpoint(configFile, rowCount, self.verifyWindowDict, self)
            verifyWin.show()
            self.verifyWindowDict[configFile] = verifyWin                     
              
    def restoreSnapshotAction(self):
        """
         QtCore.QObject.connect(self.restoreMachineButton, 
                 QtCore.SIGNAL(_fromUtf8("clicked(void)")), masar.restoreSnapshotAction)
        """    
        self.restoreMachineButton.setEnabled(False)  
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents) 
        
        restoreInfo = self.getRestoreInfo()
        if None == restoreInfo:
            return
        (eid, eid4Log, r_pvlist, r_data, r_dbrtype, r_isArray, no_restorepvs, rowCount) = restoreInfo
        
        self.simplePut(eid, eid4Log, r_pvlist, r_data, no_restorepvs, rowCount)    
                
    def rampingMachine(self):
        """
        See ui_masar.py (.ui):
QtCore.QObject.connect(self.rampingMachineButton, QtCore.SIGNAL(_fromUtf8("clicked()")), masar.rampingMachine)
        """
        #print("ramping machine")
        self.rampingMachineButton.setEnabled(False)  
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        restoreInfo = self.getRestoreInfo()
        if None == restoreInfo:
            return
        (eid, eid4Log, r_pvlist, r_data, r_dbrtype, r_isArray, no_restorepvs, rowCount) = restoreInfo
        gradualPutDlg = GradualPut(r_pvlist, r_data, r_dbrtype, r_isArray, no_restorepvs, self)   
        reply = gradualPutDlg.exec_()  
        #print(reply)
        if reply == 1:#1 means clicked QDialogButtonBox.Yes
            rampingPutResult = gradualPutDlg.rampingPut()
            if None == rampingPutResult:
                self.rampingMachineButton.setEnabled(True)
                return
            
            self.simplePut(eid, eid4Log, r_pvlist, r_data, no_restorepvs, rowCount)
        else:   
            self.rampingMachineButton.setEnabled(True)
            
#************************** End of machine restore ********************************************* 
 
    def getLiveMachineAction(self):
        """
        See ui_masar.py (.ui):
            QtCore.QObject.connect(self.getLiveMachineButton, ... , masar.getLiveMachineAction).
        getLiveMachineData() returns live timestamp, live alarm via cav3.caget.
        Comparing live machine with multiple snapshots is special, see setCompareSnapshotsTable() 
        """
        #print("%s: compare Live Machine button is clicked"%datetime.datetime.now())
        curWidget = self.snapshotTabWidget.currentWidget()
        if isinstance(curWidget, QTableWidget):
            # get event id
            eid = self.__find_key(self.tabWindowDict, curWidget)
            # 2 special case:
            if eid == 'preview':
                eid = self.previewId # get event id for preview snapshot
            elif eid == 'comment':
                self.getLiveMachineButton.setEnabled(True)
                return # nothing should do here
            elif eid == 'compare':
                #self.beCompared = True
                self.getLiveMachineButton.setEnabled(False)
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
                data_ = self.data4eid['compare']
                pvlist_ = self.pv4cDict['compare']
                eventIds_ = self.eventIds 
                #print(pvlist_)
                self.compareLiveWithMultiSnapshots = True
                self.setCompareSnapshotsTable(data_, curWidget, pvlist_, eventIds_)
                #since compareSnapshotsTable is so different from singleSnapshotTable, 
                ## don't continue and just return
                self.getLiveMachineButton.setEnabled(True)
                return
            
            self.getLiveMachineButton.setEnabled(False)
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
            #catch KeyError: 'None'
            pvlist = self.pv4cDict[str(eid)]
            
            data = self.getLiveMachineData(pvlist)
            if data:
                channelName = data[0]
                s_value = data[1]
                d_value = data[2]
                i_value = data[3]
                dbrtype = data[4]
                #isConnected = data[5]
                is_array = data[6]
                array_value = data[7]
                disConnectedPVs = data[8]
                alarm_status = data[9]
                alarm_severity = data[10]
                ts = data[11]
                ts_nano = data[12]
                #print(array_value)
                dd = {}
                noMatchedPv = []
                #disConnectedPv = []
                
                # put channel name and its order into a dictionary
                for i in range(len(channelName)):
                    dd[str(channelName[i])] = i
                
                # get table rows
                rowCount = curWidget.rowCount()
                colCount = curWidget.columnCount()
                for i in range(rowCount):
                    try:
                        index = dd[str(curWidget.item(i, 0).text())]
                        if dbrtype[index] in self.epicsNoAccess:
                            self.__setTableItem(curWidget, i, 9, "Disconnected") 
                        else:
                            self.__setTableItem(curWidget, i, 9, "Connected")              
             
                        dt=str(datetime.datetime.fromtimestamp(ts[index]+ts_nano[index]*1.0e-9)) 
                        self.__setTableItem(curWidget, i, 10, dt)
                        self.__setTableItem(curWidget, i, 11, str(alarm_status[index]))
                        self.__setTableItem(curWidget, i, 12, str(alarm_severity[index]))
                                    
                        if is_array[index]:
                            #self.__setTableItem(curWidget, i, 6, self.__arrayTextFormat(array_value[index]))
                            self.__setTableItem(curWidget, i, 4, \
                                                self.__arrayTextFormat(array_value[index]))
                            self.arrayData[channelName[index]+"_"+str(eid)+'_live'] \
                                                = array_value[index]
                            try:
                                saved_array = self.arrayData[channelName[index]+"_"+str(eid)]
                                #print("recrod %s is array:"%channelName[index])
                                #print(saved_array)
                                #print(array_value[index])
                                if str(saved_array) != str(array_value[index]):
                                    delta_ =[m - n for m, n in zip(array_value[index],saved_array)]
                                    delta_array = tuple(delta_)
                                    self.__setTableItem(curWidget, i, 5,
                                                        self.__arrayTextFormat(delta_array))
                                #print(delta) 
                                else:
                                    self.__setTableItem(curWidget, i, 5, "")    
                            except:
                                #print("something wrong with array data")
                                #delta = 'N/A'
                                self.__setTableItem(curWidget, i, 5, "N/A")
                        else:
                            if dbrtype[index] in self.epicsDouble:
                                #self.__setTableItem(curWidget, i, 6, str(d_value[index]))
                                self.__setTableItem(curWidget, i, 4, str(d_value[index]))
            
                                try:
                                    #saved_val = float(str(curWidget.item(i, 5).text()))
                                    saved_val = float(str(curWidget.item(i, 3).text()))
                                    #if d_value[index] != None:
                                    if str(d_value[index]) != str(saved_val):
                                        delta = d_value[index] - saved_val
                                        self.__setTableItem(curWidget, i, 5, str(delta))
                                    else:
                                        self.__setTableItem(curWidget, i, 5, "")
                                except:
                                    #self.__setTableItem(curWidget, i, 7, str(delta))
                                    self.__setTableItem(curWidget, i, 5, "N/A")
                            elif dbrtype[index] in self.epicsLong:
                                #self.__setTableItem(curWidget, i, 6, str(i_value[index]))
                                self.__setTableItem(curWidget, i, 4, str(i_value[index]))
            
                                if dbrtype[index] in self.epicsNoAccess:
                                    pass
                                else:
                                    try:
                                        #saved_val = int(float(str(curWidget.item(i, 5).text())))
                                        saved_val = int(float(str(curWidget.item(i, 3).text())))
                                        #if i_value[index] != None:
                                        if str(i_value[index]) != str(saved_val):
                                            delta = i_value[index] - saved_val     
                                            self.__setTableItem(curWidget, i, 5, str(delta))  
                                        else:
                                            self.__setTableItem(curWidget, i, 5, "") 
                                    except:
                                        #self.__setTableItem(curWidget, i, 7, str(delta))
                                        self.__setTableItem(curWidget, i, 5, "N/A")
                            elif dbrtype[index] in self.epicsString:
                                #self.__setTableItem(curWidget, i, 6, str(s_value[index]))   
                                #print(saved_val)  
                                self.__setTableItem(curWidget, i, 4, str(s_value[index]))
                                try:
                                    saved_val = str(curWidget.item(i, 3).text())
                                    if s_value[index] != saved_val:
                                        self.__setTableItem(curWidget, i, 5, "NotEqual")
                                    else:
                                        self.__setTableItem(curWidget, i, 5, "")
                                except:
                                    self.__setTableItem(curWidget, i, 5, "N/A")
                            else:#if dbrtype[index] in self.epicsDouble:           
                                self.__setTableItem(curWidget, i, 5, "N/A")
                    except:
                        self.__setTableItem(curWidget, i, 5, "N/A")
                        noMatchedPv.append(str(curWidget.item(i, 0).text()))
                #end of for i in range(rowCount):
                if len(noMatchedPv) > 0:
                    print ("Can not find the following pvs for this snapshot: \n", noMatchedPv)
                    QMessageBox.warning(self,"Warning",
                            "Can not find the following pvs for this snapshot: %s"%noMatchedPv)
                
                #Mark all disconnected PVs with pink color
                for i in range(rowCount):
                    try:
                        if str(curWidget.item(i, 9).text()) == "Disconnected":                   
                            self.__setTableItem(curWidget, i, 5, "N/A")  
                            for item_idx in range(colCount):
                                itemtmp = curWidget.item(i, item_idx)
                                if not itemtmp:
                                    itemtmp = QTableWidgetItem()
                                    curWidget.setItem(i, item_idx, itemtmp)
                                itemtmp.setBackground(self.brushdisconnectedpv)
                    except:
                        pass
                #sort by "Connection"  
                #curWidget.sortItems(1,0)
                #sort by "delta"  
                curWidget.sortItems(5,1)
                curWidget.resizeColumnsToContents() 
                curWidget.sortItems(9,1)
                detailedText = ""
                for i in range(len(disConnectedPVs)):
                    detailedText += '\n' + disConnectedPVs[i] 
                if len(disConnectedPVs) > 0:
                    msg = QMessageBox(self,windowTitle="Be Aware!", 
text="There are %s PVs disconnected. Click Show Details ... below for more info\n\
Or scroll down the SnapshotTab table if you like" %len(disConnectedPVs))
                    msg.setModal(False)
                    msg.setDetailedText(detailedText)
                    #msg.show()
                    msg.exec_()
                     
        else:# end of if isinstance(curWidget, QTableWidget):
            QMessageBox.warning(self, "Warning", 
                                "No snapshot is displayed. Please refer Welcome to MASAR for help")
            self.getLiveMachineButton.setEnabled(True)
            return
        
        self.getLiveMachineButton.setEnabled(True)
#************************** End of getLiveMachineAction(self) ********************************************* 
        
    def getLiveMachineData(self, pvlist):
        """
        Oct-24-2013: self.mc.getLiveMachine(params) does return live timestamp, live alarm, etc.
        
        #self.mc.getLiveMachine(params) doesn't return live timestamp, live alarm,
        #get these data via cav3.caget
        #Called by getLiveMachineAction(), setCompareSnapshotsTable(), resoreSnapshotAction()
        """
        params = {}
        for pv in pvlist:
            params[pv] = pv
        # channelName,stringValue,doubleValue,longValue,dbrType,isConnected, is_array, array_value
        array_value = []
        disConnectedPVs = []
        try:
            rpcResult = self.mc.getLiveMachine(params)
        except:
            QMessageBox.warning(self,
                                "Warning",
                                "Except happened during getting live machine.")
            #self.compareLiveWithMultiSnapshots = False
            return False
        if not rpcResult:
            QMessageBox.warning(self,
                                "Warning", 
            "Exception occurred when retieving live data, please check network or IOC status")
            return False
        channelName = rpcResult[0]
        stringValue = rpcResult[1]
        doubleValue = rpcResult[2]
        longValue = rpcResult[3]
        dbrtype = rpcResult[4]
        isConnected = rpcResult[5]
        #timestamp = rpcResult[6]
        ts = rpcResult[6]
        ts_nano = rpcResult[7]  
        severity = list(rpcResult[8])
        status = list(rpcResult[9])
        is_array = rpcResult[10]
        raw_array_value  = rpcResult[11]
        #=======================================================================
        # is_array = rpcResult[6]
        # raw_array_value = rpcResult[7]  
        # status = [""]*len(channelName)
        # severity = [""]*len(channelName)
        # timestamp = [0]*len(channelName)
        #=======================================================================
        
        for i in range(len(is_array)):
            try:
                severity[i] = self.severityDict[severity[i]]
            except:
                severity[i] = 'N/A'
            try:
                status[i] = self.alarmDict[status[i]]
            except:
                status[i] = 'N/A'
            if dbrtype[i] in self.epicsLong:
                array_value.append(raw_array_value[i][2])
            elif dbrtype[i] in self.epicsDouble:
                array_value.append(raw_array_value[i][1])
            elif dbrtype[i] in self.epicsString:
                # string value
                array_value.append(raw_array_value[i][0])
            elif dbrtype[i] in self.epicsNoAccess:
                # when the value is no_access, use the double value no matter what it is
                array_value.append(raw_array_value[i][1])
                
        # if dbrtype is NoAccess, it means that the PV is disconnected at the moment       
        for i in range(len(dbrtype)):
            if dbrtype[i] in self.epicsNoAccess:    
                disConnectedPVs.append(channelName[i])
        #=======================================================================
        #        status[i] = 'UDF_ALARM'
        #        severity[i] = 'INVALID_ALARM'
        #        timestamp[i] = 0
        #        
        # connectedPVs = list(set(channelName)-set(disConnectedPVs))
        # v3Results = cav3.caget(connectedPVs, timeout=2,format=cav3.FORMAT_TIME, throw=False)
        # for v3Result in v3Results:
        #    if v3Result.name not in channelName:
        #        QMessageBox.warning(self,"Waring",
        #                            "Exception happened in getLiveMachineData() by cav3.caget")
        #        return False
        #    pvIndex = channelName.index(v3Result.name)
        #    if v3Result.ok == True:
        #        status[pvIndex] = self.alarmDict[v3Result.status]
        #        severity[pvIndex] = self.severityDict[v3Result.severity] 
        #        timestamp[pvIndex] = v3Result.timestamp  
        #    else:
        #        status[pvIndex] = 'UDF_ALARM'
        #        severity[pvIndex] = 'INVALID_ALARM'
        #        timestamp[pvIndex] = 0
        #=======================================================================

        return (channelName,stringValue,doubleValue,longValue,dbrtype,isConnected,is_array,
                array_value,disConnectedPVs,status, severity, ts, ts_nano)
                #array_value,disConnectedPVs,status, severity, timestamp)


    def saveDataFileAction(self):
        """
        See ui_masar.py(.ui):
        QtCore.QObject.connect(self.saveDataFileButton, 
                        QtCore.SIGNAL(_fromUtf8("clicked()")), masar.saveDataFileAction)
        Save data into a file.
        """
        curWidget = self.snapshotTabWidget.currentWidget()
        if not isinstance(curWidget, QTableWidget):
            QMessageBox.warning(self, 'Warning', 
                                'No snapshot is selected. Please refer Welcome to MASAR for help')
            return
        eid = self.__find_key(self.tabWindowDict, curWidget)
        #if eid == 'comment' or eid == 'preview' or eid=="compare":
            #QMessageBox.warning(self, 'Warning', 'No data to be saved, Please select non-%s tab.'%eid)
            #return
        data = self.data4eid[str(eid)]
        
        pvnames = data['PV Name']
        status = data['Status']
        severity = data['Severity']
        ts = data['Time stamp']
        ts_nano = data['Time stamp (nano)']
        dbrtype = data['DBR']
        s_value = data['S_value']
        i_value = data['I_value']
        d_value = data['D_value']
        isConnected = data['isConnected']
        is_array = data['isArray'] 
        array_value = data['arrayValue']
        
        head = '# pv name, elem location, elem type, status, severity, time stamp, epics dbr, is connected, is array, value'

        filename = QFileDialog.getSaveFileName(self, 'Save File as .csv', '.')
        if not filename:
            return
        try:
            fname = open(filename, 'w')
            fname.write(head+'\n')
            for i in range(len(pvnames)):
                line = pvnames[i]
                # a quick, urgly solution for NSLS II naming conversion only
                # to be replaced by information from other service like channel finder
                if pvnames[i].startswith("SR:C"):
                    line += ','+pvnames[i][3:6]
                else:
                    line += ','

                if 'MG' in pvnames[i]:
                    loc1 = pvnames[i].find("{PS:")
                    loc2 =  pvnames[i][loc1:].find("}")
                    if loc1 != -1 and loc2 != 0 and loc1+4<loc1+loc2:
                        line += ','+pvnames[i][loc1+4:loc1+loc2]
                    else:
                        line += ','
                else:
                    line += ','

                # need to make above pretty and general    

                line += ','+str(status[i])
                line += ','+str(severity[i])
                line += ','+str(datetime.datetime.fromtimestamp(ts[i]+ts_nano[i]*1.0e-9))
                line += ','+str(dbrtype[i])
                line += ','+str(bool(isConnected[i]))
                line += ','+str(bool(is_array[i]))
                if is_array[i]:
                    line += ','+str(array_value[i])
                else:
                    if dbrtype[i] in self.epicsDouble:
                        line += ','+str(d_value[i])
                    elif dbrtype[i] in self.epicsLong:
                        line += ','+str(i_value[i])
                    elif dbrtype[i] in self.epicsString:
                        line += ','+str(s_value[i])
                    else:
                        line += ''

                fname.write(line+'\n')
            fname.close()
        except:
            QMessageBox.warning(self,
                                "Warning",
                                "Cannot write to the file. Please check the writing permission.") 


#************************** Start of comparing multiple snapshots ********************************* 
    def ignoreCompare(self):
        self.compareSnapshotsButton.setEnabled(True)
        pass
    
    def openMsgBox(self):  
        """
        Dialog for comparing multiple snapshots
        See ui_masar.py(.ui):
        QtCore.QObject.connect(self.compareSnapshotsButton, 
                    QtCore.SIGNAL(_fromUtf8("clicked()")), masar.openMsgBox) 
        """ 
        self.compareSnapshotsButton.setEnabled(False)
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        
        selectedEvents = self.eventTableWidget.selectionModel().selectedRows()
        ln = len(selectedEvents) 
        #print(selectedEvents)
        #print("%s events selected" %ln)
        if ln == 0:
            msg = QMessageBox(self, windowTitle="Snapshot Selection", 
                          text="Don't click OK until you have done the following:\n\n\
Select 2 ~ 9 snapshots (Ctrl key + mouse Click) from the left-bottom Snapshot Table\n\n\
If the Snapshot Table is empty, please double click on one row in the Config Table \n\n\
Click Ignore if you don't want to continue")
            okButton = msg.addButton("OK", QMessageBox.ActionRole)
            quitButton = msg.addButton(QMessageBox.Ignore)
            msg.setAttribute(Qt.WA_DeleteOnClose)
            msg.setModal(False)
            msg.show()
            #msg.open(self, SLOT(msgBoxClosed()))
            #msg.open.connect(self.msgBoxClosed)
            okButton.clicked.connect(self.compareSnapshots) 
            quitButton.clicked.connect(self.ignoreCompare) 
            #msg.buttonClicked.connect(self.compareSnapshots)    
            #print("QMessageBox is closed")        
        elif ln >=2 and ln <= 9:
            self.compareSnapshots()
        
        elif ln >0 and ln <2 or ln > 9:
            QMessageBox.warning(self,"Waring", 
                                "Please select 2 ~ 9 snapshots for comparison,not %d snapshots"%ln) 
            self.compareSnapshotsButton.setEnabled(True)
            return       
 
    
    def compareSnapshots(self):
        selectedEvents = self.eventTableWidget.selectionModel().selectedRows()
        ln = len(selectedEvents) 
        if ln == 0:
            self.compareSnapshotsButton.setEnabled(True)
            return
        #print(selectedEvents)
        elif ln < 2 or ln > 9:
            QMessageBox.warning(self,"Waring", 
                                "Please select 2 ~ 9 snapshots for comparison,not %d snapshots"%ln) 
            self.compareSnapshotsButton.setEnabled(True)
            return
        #print("compare %d snapshots" %ln)
        #eventTs=[]
        eventNames=[]
        eventIds = []
        data = []
        self.compareId = None
        self.compareConfName =  None        
        for idx in selectedEvents: 
            eventNames.append(str(self.eventTableWidget.item(idx.row(), 0).text()))
            #eventTs.append(str(self.eventTableWidget.item(idx.row(), 3).text()))
            eventIds.append(str(self.eventTableWidget.item(idx.row(), 1).text()))  
        #print(eventNames)
        #print(eventIds)    
        #for eventId in eventIds:
        msg = QMessageBox(self, windowTitle="Select one reference snapshot", 
text="Snapshots comparison is made between the reference snapshot and other snapshots:\n\n\
Snapshot %s is the reference since you clicked it first, click OK to keep it as it\n\n\
Otherwise click Change the ref. snapshot ..."%eventIds[0])
        msg.addButton("Change the ref. snapshot ...",QMessageBox.AcceptRole)
        msg.addButton("OK", QMessageBox.RejectRole) 
        ret = msg.exec_()
        #print(ret)
        if ret == 0:
            reorderedIDs = self.selectRefSnapshot(eventIds)
            #print("reorderedIDs: %s"%reorderedIDs)
            if reorderedIDs:
                eventIds = reorderedIDs
        #print("eventIds: %s"%eventIds)    
        self.eventIds = eventIds
        for i in range(len(eventIds)):
            result = self.retrieveMasarData(eventid = eventIds[i])
            if result == None or not isinstance(result, odict) :
                QMessageBox.warning(self,"Warning",
                                    "Failed to retrieve data for snapshot %s"%eventIds[i])
                self.compareSnapshotsButton.setEnabled(True)
                return
            else:
                data.append(result) 
        #save data to dictionary for future retrieval (i.e. getLiveMachineAction()) 
        self.data4eid['compare'] = data
        #data is a list with odict elements; data[i] is an odict;
        #data[i]['keyword'] is a tuple; data[i]['keyword'][index] is the element value in the tuple                   
        #print (data)
        #print(data[0]['PV Name'])
        
        #try:
        if self.tabWindowDict.has_key('compare'):
            tableWidget = self.tabWindowDict['compare']
            #index = self.snapshotTabWidget.indexOf(tableWidget)  
        #except:
        else:
            tableWidget = QTableWidget()
            #index = self.snapshotTabWidget.count()
            self.tabWindowDict['compare'] = tableWidget
            QObject.connect(tableWidget, SIGNAL(_fromUtf8("cellDoubleClicked (int,int)")), 
                            self.__showArrayData)
        labelText = ""
        for eventId in eventIds:
            labelText += '_' + eventId
        label = QString.fromUtf8("Compare Snapshots: IDs" + labelText)
        self.snapshotTabWidget.addTab(tableWidget, label)
        #self.snapshotTabWidget.setTabText(index, label)
        self.snapshotTabWidget.setTabText(self.snapshotTabWidget.count(), label)
        self.snapshotTabWidget.setCurrentIndex(self.snapshotTabWidget.count())
        self.snapshotTabWidget.setCurrentWidget(tableWidget)
        #print("%d tabs when compareSnapshots"%self.snapshotTabWidget.count())
        self.resizeSplitter(1)
        #assert(data != None and isinstance(tabWidget, QTableWidget))
        #print("configure the table for comparing multiple snapshots")
        #tabWidget.setSortingEnabled(False)
        #tabWidget.clear()
        keys = ['PV name']
        #pvList = odict()
        pvList = []
        #pvList = list(data[0]['PV Name'])
        nEvents = len(data)
        #print("compare %d event data"%nEvents)
        for i in range(nEvents):
            #keys.append("Saved Value in Snapshot"+str(i+1)+"\n"+"("+str(eventNames[i][0:18])+"...:"+str(eventIds[i])+")")
            #keys.append("Timestamp in Snapshot"+str(i+1)+"\n"+"("+str(eventNames[i][0:18])+"...:"+str(eventIds[i])+")")
            keys.append("Saved Value "+str(i+1)+"\n"+"(" + "in snapshot "+str(eventIds[i])+")")
            #keys.append("Timestamp "+str(i+1)+"\n"+"(" + "in Event "+str(eventIds[i])+")")
            #use .extend instead of .append here
            #pvList.extend(list(data[i]['PV Name']))
        keys.append('Live Value 0')
        nDelta = nEvents - 1
        for i in range(nDelta):
            keys.append("Delta%s1"%str(i+2))      
        keys.append('Delta01') 
        for i in range(nEvents):
            keys.append("Timestamp "+str(i+1)+"\n"+"(" + "in snapshot "+str(eventIds[i])+")")
        self.compareSnapshotsTableKeys  = keys
        #print(keys)
        #print("%d PVs after merging without removing duplicates"%len(pvList))
        #pvSet = set(pvList)
        #pvList = list(pvSet)
        pvList = list(data[0]['PV Name'])
        self.pv4cDict['compare'] = pvList
        #print("%d PVs after removing duplicates"%len(pvList))
        #print("data in compareSnapshots: ")
        #print(data   
        nRows = len(pvList)
        nCols = len(keys) 
        tableWidget.setRowCount(nRows)
        tableWidget.setColumnCount(nCols)
        #tabWidget.setHorizontalHeaderLabels(keys)  
        #self.setCompareSnapshotsTable(data, tabWidget, eventNames[0])    
        #self.setCompareSnapshotsTable(data, tabWidget, eventNames, eventIds)
        self.setCompareSnapshotsTable(data, tableWidget, pvList, eventIds)  
        tableWidget.resizeColumnsToContents()  
        tableWidget.setStatusTip("compare %d snapshots with snapshotIds:%s"%(nEvents,eventIds))
        tableWidget.setToolTip("delta21: value in 2nd snapshot - value in 1st snapshot\n\
delta01: live value - value in 1st snapshot")
        #tabWidget.setSortingEnabled(True)   
        #tabWidget.setColumnWidth(1, 80)
        #tabWidget.resizeRowsToContents()  
        #self.compareId = eid    
        #self.compareConfName =  None
        self.compareSnapshotsButton.setEnabled(True)

    def selectRefSnapshot(self, eventIDs):
        #print(eventIDs)
        dlg = ShowSelectRefDlg(eventIDs)
        dlg.exec_()
        if dlg.isAccepted:
            #print(dlg.result())
            return(dlg.result())

    def setCompareSnapshotsTable(self, data, table, pvlist, eventIds):
        assert(data!=None and isinstance(table,QTableWidget) and pvlist!=None and len(eventIds)>=2)
        pvList = pvlist
        #print("data in setCompareSnapshotsTable: ")
        #print(data)
        nRows = len(pvList)
        nEvents = len(data) 
        #must have the following two lines, otherwise the sorting will make data messed up
        table.setSortingEnabled(False)
        table.clear()
        keys = self.compareSnapshotsTableKeys
        table.setHorizontalHeaderLabels(keys) 
         
        #for i,j in range(nRows), range(nEvents):
        for i in range(nRows):
            self.__setTableItem(table, i, 0, pvList[i])
            #print(i,    pvList[i])
            for j in range(nEvents):
                if pvList[i] in data[j]['PV Name']:  
                    pvIndex = data[j]['PV Name'].index(pvList[i])
                    #if pvIndex: 
                    #data is a list with odict elements; data[j] is an odict;
                    #data[j]['keyword'] is a tuple; data[j]['keyword'][index] is a single item/value  
                    if data[j]['Time stamp'][pvIndex]:
                        dt = str(datetime.datetime.fromtimestamp(data[j]['Time stamp'][pvIndex] + \
                                                    data[j]['Time stamp (nano)'][pvIndex]*1.0e-9))
                        #self.__setTableItem(table, i, 2*(j+1), dt)
                        self.__setTableItem(table, i, 2*(nEvents+1)+j, dt)
                    if data[j]['isArray'][pvIndex]:
                        #self.__setTableItem(table, i, 2*j+1, self.__arrayTextFormat(data[j]['arrayValue'][pvIndex]))   
                        self.__setTableItem(table, i, j+1, \
                                        self.__arrayTextFormat(data[j]['arrayValue'][pvIndex]))
                        #print(table.item(i,j+1).text())
                        self.arrayData[pvList[i]+'_'+str(eventIds[j])+'_compare'] \
                                                                  =data[j]['arrayValue'][pvIndex] 
                        #print(self.arrayData)
                        try:
                            ref_wf = data[0]['arrayValue'][pvIndex] 
                            if j >0 and str(data[j]['arrayValue'][pvIndex])!=str(ref_wf):
                                delta = [m-n for m,n in zip(data[j]['arrayValue'][pvIndex],ref_wf)]
                                delta_array = tuple(delta)
                                self.__setTableItem(table, i,nEvents+1+j, \
                                                    self.__arrayTextFormat(delta_array)) 
                        except:
                            self.__setTableItem(table, i,nEvents+1+j,"N/A")
                                
                    elif data[j]['DBR'][pvIndex] in self.epicsDouble:
                        #self.__setTableItem(table, i, 2*j+1, str(data[j]['D_value'][pvIndex]))
                        self.__setTableItem(table, i, j+1, str(data[j]['D_value'][pvIndex]))
                        try:
                            if j>0 and str(table.item(i,1).text())!=str(data[j]['D_value'][pvIndex]):
                                delta=data[j]['D_value'][pvIndex]-float(str(table.item(i,1).text())) 
                                #self.__setTableItem(table, i,2*(nEvents+1)+j-1,str(delta))
                                self.__setTableItem(table, i,nEvents+1+j,str(delta))
                        except:
                            self.__setTableItem(table, i,nEvents+1+j,"N/A")
                            
                    elif data[j]['DBR'][pvIndex] in self.epicsLong:
                        #self.__setTableItem(table, i, 2*j+1, str(data[j]['I_value'][pvIndex]))
                        self.__setTableItem(table, i, j+1, str(data[j]['I_value'][pvIndex]))
                        try:
                            if j>0 and str(table.item(i,1).text())!=str(data[j]['I_value'][pvIndex]):
                                delta=data[j]['I_value'][pvIndex] - int(str(table.item(i,1).text())) 
                                #self.__setTableItem(table, i,2*(nEvents+1)+j-1,str(delta))
                                self.__setTableItem(table, i,nEvents+1+j,str(delta))
                        except:
                            self.__setTableItem(table, i,nEvents+1+j,"N/A")
                            
                    elif data[j]['DBR'][pvIndex] in self.epicsString:
                        #self.__setTableItem(table, i, 2*j+1, str(data[j]['S_value'][pvIndex]))
                        self.__setTableItem(table, i, j+1, str(data[j]['S_value'][pvIndex]))
                        try:
                            if j>0 and str(table.item(i,1).text())!=str(data[j]['S_value'][pvIndex]):
                                #self.__setTableItem(table, i,2*(nEvents+1)+j-1,str(delta))
                                self.__setTableItem(table, i,nEvents+1+j,str("NotEqual"))
                        except:
                            self.__setTableItem(table, i,nEvents+1+j,"N/A")
                    #elif data[j]['DBR'][pvIndex] in self.epicsNoAccess:
                        #self.__setTableItem(table, i,nEvents+2+j,"N/A")
                    elif j > 0:
                        self.__setTableItem(table, i,nEvents+1+j,"N/A")
                    else:
                        self.__setTableItem(table, i,nEvents+2+j,"N/A")
                 
                else:#if pvList[i] in data[j]['PV Name']:
                    self.__setTableItem(table, i,nEvents+1+j,"N/A")  
                #print(pvIndex,data[j]['D_value'][pvIndex])   
                
        #have to wait 2 seconds before calling getLiveMachineData() if the snapshot has big data set 
        #QThread.sleep(2)
        #QThread.usleep(10000)
        #Sleep(1)
        #self.compareLiveWithMultiSnapshots is set to True in getLiveMachineAction()
        if self.compareLiveWithMultiSnapshots:
            self.compareLiveWithMultiSnapshots = False                                 
            liveData = self.getLiveMachineData(pvList)
            if liveData:
                #print(liveData)
                channelName = liveData[0]
                s_value = liveData[1]
                d_value = liveData[2]
                i_value = liveData[3]
                dbrtype = liveData[4]
    #           isConnected = data[5]
                is_array = liveData[6]
                array_value = liveData[7]
                #print(pvList)
                #print(channelName)
                for i in range(nRows):
                    if pvList[i] in channelName:
                        liveIndex = channelName.index(pvList[i])
                        if is_array[liveIndex]:
                            #self.__setTableItem(table, i, 2*nEvents+1, self.__arrayTextFormat(array_value[liveIndex]))
                            self.__setTableItem(table, i, nEvents+1, \
                                                self.__arrayTextFormat(array_value[liveIndex]))
                            self.arrayData[pvList[i]+'_compare'+'_live']=array_value[liveIndex]
                            try:
                                pvIndex = data[0]['PV Name'].index(pvList[i])
                                ref_wf = data[0]['arrayValue'][pvIndex]
                                if str(ref_wf) != str(array_value[liveIndex]):
                                    delta=[m-n for m,n in zip(ref_wf,array_value[liveIndex])]
                                    delta_array = tuple(delta)
                                    self.__setTableItem(table,i,2*nEvents+1, \
                                                        self.__arrayTextFormat(delta_array))
                            except:
                                self.__setTableItem(table, i,2*nEvents+1,str("N/A")) 
                                
                        elif dbrtype[liveIndex] in self.epicsDouble:
                            #self.__setTableItem(table, i, 2*nEvents+1, str(d_value[liveIndex]))
                            self.__setTableItem(table, i, nEvents+1, str(d_value[liveIndex]))
                            try:
                                if str(table.item(i,1).text()) != str(d_value[liveIndex]):
                                    delta = d_value[liveIndex] - float(str(table.item(i,1).text()))
                                    self.__setTableItem(table, i,2*nEvents+1,str(delta))  
                            except:
                                self.__setTableItem(table, i,2*nEvents+1,str("N/A"))
                                       
                        elif dbrtype[liveIndex] in self.epicsLong:
                            #self.__setTableItem(table, i, 2*nEvents+1, str(i_value[liveIndex]))
                            self.__setTableItem(table, i, nEvents+1, str(i_value[liveIndex]))
                            try:
                                if str(table.item(i,1).text()) != str(i_value[liveIndex]):
                                    delta = i_value[liveIndex] - int(str(table.item(i,1).text()))   
                                    self.__setTableItem(table, i,2*nEvents+1,str(delta)) 
                            except:
                                self.__setTableItem(table, i,2*nEvents+1,str("N/A"))
                                
                        elif dbrtype[liveIndex] in self.epicsString:
                            #self.__setTableItem(table, i, 2*nEvents+1, str(s_value[liveIndex]))
                            self.__setTableItem(table, i, nEvents+1, str(s_value[liveIndex]))
                            try:
                                if str(table.item(i,1).text()) != str(s_value[liveIndex]):    
                                    self.__setTableItem(table, i,2*nEvents+1,str("NotEqual"))
                            except:
                                self.__setTableItem(table, i,2*nEvents+1,str("N/A"))
                        elif dbrtype[liveIndex] in self.epicsNoAccess:
                            self.__setTableItem(table, i,2*nEvents+1,str("N/A"))
                        else:
                            self.__setTableItem(table, i,2*nEvents+1,str("N/A"))
                            
                    else:#if pvList[i] in channelName:
                        self.__setTableItem(table, i,2*nEvents+1,str("N/A"))
            table.setSortingEnabled(True)
            table.sortItems(2*nEvents+1, 0)
        else:#if self.compareLiveWithMultiSnapshots:
            table.setSortingEnabled(True)      
            #table.sortItems(3*nEvents+1, 1)
            table.sortItems(nEvents+2, 0)
#************************** End of comparing multiple snapshots *********************************** 

    #def restoreFilterChanged(self):
        #self.currentRestoreFilter = str(self.restoreFilterLineEdit.text())
        
    #def partialRestoreMachine(self):
        #print("restore filter: %s"%(self.currentRestoreFilter))

    def pvFilterChanged(self):
        self.currentPvFilter = str(self.pvFilterLineEdit.text())
        #self.pvFilterLineEdit.returnPressed.connect(self.searchPV)
 
    def getInfoFromTableWidget(self):
        curWidget = self.snapshotTabWidget.currentWidget()
        if not isinstance(curWidget, QTableWidget):
            QMessageBox.warning(self, "Warning", 
                                "No snapshot is displayed. Please refer Welcome to MASAR for help")
            return None
        
        eid = self.__find_key(self.tabWindowDict, curWidget)
        if eid == 'comment':
            return
        if eid == 'preview':
            eid = self.previewId 
        if eid == 'compare':
            QMessageBox.warning(self, "Warning", 
                                "Sorry, pv searching on compareSnapshotTab is not supported yet")    
            return            
            
        data_ = self.data4eid[str(eid)]#'filter' is an eid
        pvlist_ = self.pv4cDict[str(eid)]  
        eventIds_ = self.eventIds 
        config_ = self.e2cDict[eid]
        return(data_, pvlist_, eid, eventIds_, config_)        
               
    def searchPV(self):
        data = odict()
        #print("pv filter: %s"%(self.currentPvFilter))
        pattern_ = self.currentPvFilter
        pattern = fnmatch.translate(pattern_)
        #pattern = 'r'+`pattern_` 
        #print("pattern: %s"%(pattern))
        #if pattern == '*':
            #pattern = ""   
             
        info = self.getInfoFromTableWidget()
        if info == None:
            return 
        if str(info[2]).isdigit():
            self.origID = str(info[2])
            self.e2cDict['filter'] = info[4]              
        pvList = info[1]
        #print(pvList) 
        #print("info[0]")
        #print(info[0]['PV Name'])
        #print("%d PVs in the orignal tab \n"%(len(pvList)))
        regex = re.compile(pattern, re.IGNORECASE)
        filteredPVs = [pv for pv in pvList for m in [regex.search(pv)] if m]
        #print(filteredPVs) 
        if 0 == len(filteredPVs):
            QMessageBox.warning(self, "Warning", 
"No matching pv. Did you forget to use * at the beginning / the end of your search characters?\n\n\
Please refer Welcome to MASAR tab for help, then re-enter your search pattern.")
            return          
        
        #print(str(info[2])) 
        if str(info[2]) == 'filter':   
            label = "filtered snapshot(ID_" + self.origID + "_filter)" 
        else:
            label = "filtered snapshot(ID_" + str(info[2]) + ")" 
            
        tableWidget = self.createNewTableWidget("filter", label)
        
        status,severity,ts,ts_nano,dbr,sval,ival,dval,isCon,isArr,arr = [],[],[],[],[],[],[],[],[],[],[]
        for i in range(len(filteredPVs)):
            index = info[0]['PV Name'].index(filteredPVs[i])
            status.append(info[0]['Status'][index])
            severity.append(info[0]['Severity'][index])
            ts.append(info[0]['Time stamp'][index])
            ts_nano.append(info[0]['Time stamp (nano)'][index])
            dbr.append(info[0]['DBR'][index])
            sval.append(info[0]['S_value'][index])
            ival.append(info[0]['I_value'][index])
            dval.append(info[0]['D_value'][index])
            isCon.append(info[0]['isConnected'][index])
            isArr.append(info[0]['isArray'][index])
            arr.append(info[0]['arrayValue'][index])
            
        data['PV Name'] = filteredPVs
        data['Status'] = status
        data['Severity'] = severity
        data['Time stamp'] = ts
        data['Time stamp (nano)'] = ts_nano
        data['DBR'] = dbr
        data['S_value'] = sval
        data['I_value'] = ival
        data['D_value'] = dval
        data['isConnected'] = isCon
        data['isArray'] = isArr
        data['arrayValue'] = arr 
        
        self.pv4cDict['filter'] = data['PV Name']#eventID: numbers, 'filter'    
        self.data4eid['filter'] = data#'filter' is an eventID     
        
        tableWidget.clear()
        self.setSnapshotTable(data, tableWidget, 'filter')
        #tableWidget.resizeColumnsToContents()
    
    def setGoldenSnapshot(self):
        if self.userID not in masarConfigDict["OperatorList"]["account"]:
            QMessageBox.warning(self, "Warning", \
                        "You DO NOT have the privilege to set golden snapshot")
            return
        selectedItems = self.eventTableWidget.selectionModel().selectedRows()
        if len(selectedItems) != 1:
            QMessageBox.warning(self, "Warning", \
                "Please select one and only one snapshot to be set as Golden")
            return          
        if not self.getAuthentication():
            return  
        eventID = str(self.eventTableWidget.item(selectedItems[0].row(), 1).text())    
        configName = str(self.eventTableWidget.item(selectedItems[0].row(), 0).text())
        #print(eventID)  
        goldenDataFile = self.goldenDataFilePath + "goldenSnapshotOf" + configName + ".data"
        logText = eventID + " # " + configName + " marked as Golden snapshot at " + \
                  str(datetime.datetime.now()) + " by " + self.userID + "\n"
        try: 
            umask_original = os.umask(0) #needed to solve permission issue
            fdesc = os.open(goldenDataFile,os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o666)
            os.umask(umask_original)
            fd = os.fdopen(fdesc,'a')
            fd.write(logText)
            fd.close()
            fd = open(goldenDataFile, 'r')
            lines = fd.readlines()
            fd.close()
            for line in lines[:-1]:
                if eventID in line:
                    lines.remove(line) #remove dumplicated entries
                    fd = open(goldenDataFile, 'w')
                    fd.writelines(lines) 
                    fd.close()                
            if len(lines) > 10: # keep 10 golden snapshots
                fd = open(goldenDataFile, 'w')
                fd.writelines(lines[-10:]) 
                fd.close()   
        except:
            traceback.print_exc()
            QMessageBox.warning(self, "Warning", \
                "Failed to tag the selected snapshot as golden")     
            return
        QMessageBox.warning(self, "Congrats", \
"SnapshotID %s has been successfully marked as Gold. \
You may click 'Display Golden Snapshot' to confirm this"%eventID)    
        self.createLogEntry(logText)         
    
    def fetchGoldenSnapshotAction(self):
        try:
            self._fetchGoldenSnapshotAction()
        except:
            traceback.print_exc()        
    
    def _fetchGoldenSnapshotAction(self):
        selectedConfigs = self.configTableWidget.selectionModel().selectedRows()
        if len(selectedConfigs) != 1:
            QMessageBox.warning(self, "Warning", \
                "Please select one and only one Config to get a golden snapshot")
            return         
        configName = str(self.configTableWidget.item(selectedConfigs[0].row(), 0).text())
        goldenDataFile = self.goldenDataFilePath + "goldenSnapshotOf" + configName + ".data"
        if not (os.path.isfile(goldenDataFile)):
            QMessageBox.warning(self, "Warning", \
                "No golden snapshot has been tagged yet. Please set one snapshot\
 as Golden first")
            return
        fd = open(goldenDataFile, 'r')
        lines = fd.readlines()
        fd.close() 
        goldenID = lines[-1].split('#')[0].strip()
        #eventOrder = [] # a list of numbers (not strings)
        #for line in lines:
        #    eventOrder.append(int(line.split('#')[0].strip()))
        #eventOrder.reverse()    
        #print(eventOrder)
        self.fetchEventAction()
        self.retrieveSnapshotById(goldenID)
        
 #end of class masarUI       
        
        
def main(channelname = None):
    #print("%s: after main()"%datetime.datetime.now())
    app = QApplication(sys.argv)
    #app = cothread.iqt() 
    app.setOrganizationName("NSLS II")
    app.setOrganizationDomain("BNL")
    app.setApplicationName("MASAR Viewer")
    if channelname:
        form = masarUI(channelname=channelname)
    else:
        form = masarUI()
    #print("%s: after form=masarUI()"%datetime.datetime.now())
    hostname = platform.node()
    title = "MASAR Viewer on " + str(hostname) + " for MASAR Server " + str(channelname)
    form.setWindowTitle(title)
    form.show()
    #print("%s: after form.show()"%datetime.datetime.now())
    #form.showMaximized()
    app.exec_()
    #print("%s: after app.exec_()"%datetime.datetime.now())
    
    import atexit
    # clean Python local objects first, especially the cothread stuff.
    # Cothread adds a new function in catools._catools_atexit(), ca_flush_io(), since version 2.8
    # to flush all io and do a clean up. This function registered at Python exit, and will be called 
    # by Python exit handler.
    # This forces the clean up has be done before calling epicsExit(). 
    atexit._run_exitfuncs()

    # it is safe to clean epics objects now.
    epicsExit()
    
    # call os.exit() instead of sys.exit()
    # os._exit(0)
    # however, os._exit() does nothing when exiting.
    # It would be better to call sys.exit
    sys.exit()
    #print("%s: after sys.exit()"%datetime.datetime.now())

if __name__ == '__main__':
    args = sys.argv[1:]
    while args:
        arg = args.pop(0)
        if arg in ("-h", "--help", "help"):
            usage()
        else:
            print ('Unknown option.')   

    main()
