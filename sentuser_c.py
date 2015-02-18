#!/usr/bin/env python

import sys
import os.path
import time
import struct
import glob
import os
import bisect
import datetime
import shutil
import signal
import select
import dircache
import math
import pango

from subprocess import *

import Image
import ImageChops

try:
    import pygtk
    pygtk.require("2.0")
except:
    pass
try:
    import gtk
    import gtk.glade
except:
    sys.exit(1)
    
import gobject

GLOB_STRING = os.path.join(os.path.join( os.environ.get("HOME"), "events" ),"s*_???.txt")

def ReadPalette():
    f = file("CLUT.txt")
    lines = f.readlines()
    triplets = [ map(int,l.split()) for l in lines ]
    triplets.reverse()
    x = []
    map(x.extend,triplets)
    return x

class SentinelGTK:
    """This is a GTK application"""

    def __init__(self):
		
        #Set the Glade file
        self.gladefile = "sentinel.glade"  
        self.wTree = gtk.glade.XML(self.gladefile) 
		
        #Create our dictionay and connect it
        dic = { "on_StartButton_toggled"      : self.startButton_toggled,
		"on_MainWindow_destroy"       : self.Quit,
		"on_dialog1_delete_event"     : self.DeleteDisplaySettings,
		"on_dialog2_delete_event"     : self.DeleteEventSettings,
                "on_dialog3_delete_event"     : self.DeleteReplayArchive,
		"on_Replay_clicked"           : self.NewReplay,
		"on_FirstButton_clicked"      : self.PlayFirst,
		"on_PreviousButton_clicked"   : self.PlayPrevious,
		"on_NextButton_clicked"       : self.PlayNext,
		"on_LastButton_clicked"       : self.PlayLast,
		"on_CompositeButton_clicked"  : self.ShowComposite,
		"on_DeleteButton_clicked"     : self.Delete,
                "on_quit1_activate"           : self.Quit,
                "on_open1_activate"           : self.openEvent,
		"on_savemovie_activate"       : self.SaveTimeHistory,
		"on_savejpeg_activate"        : self.SaveJPEG,
		"on_savetiff_activate"        : self.SaveTIFF,
                "on_savemask_activate"        : self.SaveMaskPGM,
		"on_First_activate"           : self.PlayFirst,
		"on_Next_activate"            : self.PlayNext,
		"on_Previous_activate"        : self.PlayPrevious,
		"on_Last_activate"            : self.PlayLast,
		"on_Replay_activate"          : self.NewReplay,
		"on_Composite_activate"       : self.ShowComposite,
		"on_Delete_activate"          : self.Delete,
		"on_displaysettings_activate" : self.ShowDisplaySettings,
		"on_displayOK_clicked"        : self.OK_DisplaySettings,
		"on_displayCancel_clicked"    : self.CancelDisplaySettings,
		"on_displayApply_clicked"     : self.ApplyDisplaySettings,
		"on_eventsettings_activate"   : self.ShowEventSettings,
		"on_eventOK_clicked"          : self.OK_EventSettings,
		"on_eventCancel_clicked"      : self.CancelEventSettings,
                "on_replay_archive_activate"  : self.ShowReplayArchive,
                "on_closebutton_clicked"      : self.HideReplayArchive,
                "on_radiotoolbuttonStop_clicked"    : self.Handle_VCR_Stop,
                "on_radiotoolbuttonForward_clicked" : self.Handle_VCR_Forward,
                "on_radiotoolbuttonFast_clicked"    : self.Handle_VCR_Fast,
                "on_toolbuttonSave_clicked"         : self.Handle_VCR_Save
		 }
        self.wTree.signal_autoconnect(dic)
	
	lbl = self.wTree.get_widget("MainLabel")
        lbl.modify_font( pango.FontDescription("monospace") )
        lbl = self.wTree.get_widget("SubLabel")
        lbl.modify_font( pango.FontDescription("monospace") )

        self.csentinel = None
	self.current_path = None
	self.raw_image = None
        self.event_play_list = []
        self.event_jpeg_file = None
        self.vcr_file = None
        self.vcr_fast = False
        self.vcr_start_time = 0
        self.vcr_time = time.time()
	self.timeout = None
	self.periodic = None
	self.slowdown = 1
	self.hourly_rate = 12
	self.disable_time = datetime.time(6,0,0)
	self.enable_time = datetime.time(18,0,0)
	self.frame_index = 0
	self.img = self.wTree.get_widget( "image1" )
	self.img.set_from_file( "wagon.tif" )
	self.img.set_double_buffered( False )
	self.palette = ReadPalette()
        self.gray_scale = False
	self.displayDialog = self.wTree.get_widget("dialog1")
	self.eventDialog = self.wTree.get_widget("dialog2")
        self.replayArchiveDialog = None
        self.recent_events = glob.glob(GLOB_STRING)
        self.triggered = False
        self.triggerCount = 0
        self.previous = None
        self.eventFile = None
	self.GetEventSettings()

    def Quit( self, widget ):
        if self.event_jpeg_file:
           os.kill(self.event_jpeg_file.pid, signal.SIGTERM)
           self.event_jpeg_file = None
            
        gtk.main_quit( widget )

    def DiskUsage( self ):
        path = os.path.join( os.environ.get("HOME"), "images" )
        cmd = "df %s" % path
        f = os.popen( cmd, "r" )
        lines = f.readlines()
        items = lines[1].split()
        percent = int(items[4][:-1])
        return percent

    def TimeFormat( self, t, msec ):
        fmt = "%m/%d/%Y %H:%M:%S"
        s = time.strftime( fmt, time.localtime(t) )
        if msec:
            s += ".%03d" % int(math.modf(t)[0]*1000)
        return s

    def DeleteEarliest( self ):
        path1 = os.path.join( os.environ.get("HOME"), "images" )
        if not os.path.exists( path1 ):
            return

        deleted = False
        for folder1 in dircache.listdir( path1 ):
            if deleted:
                break

            path2 = os.path.join( path1, folder1 )

            for folder2 in dircache.listdir( path2 ):
                if deleted:
                    break

                path3 = os.path.join( path2, folder2 )
                glist = glob.glob( os.path.join( path3, "s????????_???.jpg" ) )

                for fpath in glist:
                    upath = os.path.join( path3, "a" + os.path.basename(fpath)[1:-4] + ".txt" )
                    if not os.path.exists( upath ):
                        os.remove( fpath )
                        deleted = True

                if len( dircache.listdir( path3 ) ) == 0:
                    os.rmdir( path3 )     

            if len( dircache.listdir( path2 ) ) == 0:
                os.rmdir( path2 )         
                    

    def FindNearestStrip( self, name ):
        # print "Nearest: %s" % name
        name = name.strip() 
        path = os.path.join( os.environ.get("HOME"), "images" )
        if not os.path.exists( path ):
            return None

        path1 = os.path.join( path, name[:-12] )
        if not os.path.exists( path1 ):
            items = dircache.listdir( path )
            items.sort()
            i = bisect.bisect( items, name[:-12] )
            if i >= len(items):
               return None

            name = "%s0000_000.jpg" % items[i]
            # print "Name: %s" % name
            path1 = os.path.join( path, items[i] )
            # print "Path1: %s" % path1

        path2 = os.path.join( path1, name[:-10] )
        if not os.path.exists( path2 ):
            items = dircache.listdir( path1 )
            items.sort()
            i = bisect.bisect( items, name[:-10] )
            if i >= len(items):
                num = int( name[1:-12], 16 ) + 1
                name = "s%04x0000_000.jpg" % num
                return self.FindNearestStrip( name )

            name = "%s00_000.jpg" % items[i]
            # print "Name: %s" % name
            path2 = os.path.join( path1, items[i] )
            # print "Path2: %s" % path2

        items = dircache.listdir( path2 )
        items.sort()
        i = bisect.bisect( items, name )
        if i >= len(items):
            num = int( name[1:-8], 16 ) + 1
            name = "s%08x_000.jpg" % num
            return self.FindNearestStrip( name )

        path3 = os.path.join( path2, items[i] )   
        # print "Path3: %s" % path3
        return path3     

    def Handle_VCR_Stop( self, widget ):
        if not widget.get_active():
            return

        if self.event_jpeg_file:
           os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
           self.event_jpeg_file = None
           self.frame_index = 0

	if self.timeout:
	    gobject.source_remove( self.timeout )
	    self.timeout = None

        self.vcr_file = None
        return True

    def VCR_Common( self ):
        calendar   = self.wTree.get_widget( "calendar" )
        spinHour   = self.wTree.get_widget( "spinbuttonHour" )
        spinMinute = self.wTree.get_widget( "spinbuttonMinute" )
        spinSecond = self.wTree.get_widget( "spinbuttonSecond" )
        spinDuration = self.wTree.get_widget( "spinbuttonDuration" )
        year, month, day = calendar.get_date()
        hour   = spinHour.get_value_as_int()
        minute = spinMinute.get_value_as_int()
        second = spinSecond.get_value_as_int()

        duration = spinDuration.get_value_as_int()

        tup = (year,month+1,day,hour,minute,second,0,1,-1)
        t = time.mktime( tup )
        self.vcr_start_time = t

        s = "s%08x_000.jpg" % int(t + duration)

        if self.event_jpeg_file:
           os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
           self.event_jpeg_file = None
           self.frame_index = 0

	if self.timeout:
	    gobject.source_remove( self.timeout )
	    self.timeout = None

        self.vcr_file = self.FindNearestStrip( s )
        if self.vcr_file:
	    self.timeout = gobject.timeout_add( 20*self.slowdown, self.PlayVCR_Next)
        return True

    def Handle_VCR_Forward( self, widget ):
        if not widget.get_active():
            return True

        self.vcr_fast = False
        return self.VCR_Common()

    def Handle_VCR_Fast( self, widget ):
        if not widget.get_active():
            return True

        self.vcr_fast = True
        return self.VCR_Common()

    def Handle_VCR_Save( self, widget ):
        if self.event_jpeg_file:
           os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
           self.event_jpeg_file = None
           self.frame_index = 0

	if self.timeout:
	    gobject.source_remove( self.timeout )
	    self.timeout = None

        calendar   = self.wTree.get_widget( "calendar" )
        spinHour   = self.wTree.get_widget( "spinbuttonHour" )
        spinMinute = self.wTree.get_widget( "spinbuttonMinute" )
        spinSecond = self.wTree.get_widget( "spinbuttonSecond" )
        spinDuration = self.wTree.get_widget( "spinbuttonDuration" )
        year, month, day = calendar.get_date()
        hour   = spinHour.get_value_as_int()
        minute = spinMinute.get_value_as_int()
        second = spinSecond.get_value_as_int()

        duration = spinDuration.get_value_as_int()

        tup = (year,month+1,day,hour,minute,second,0,1,-1)
        t = time.mktime( tup )
 
        eventName = "s%08x_000.txt" % int(t)
        path = os.path.join( os.environ.get("HOME"), "events" )
        path = os.path.join( path, eventName )
        eventFile = file( path, "w" )

        s1 = "s%08x_000.jpg" % int(t-1)

        t2 = t + duration

        while 1:
            sfile1 = self.FindNearestStrip( s1 )
            if not sfile1:
                break;

            s1 = os.path.basename(sfile1)
            eventFile.write( "%s\n" % s1 )
            self.RegisterUsage( s1 )

            t1 = int(sfile1[-16:-8],16) + int(sfile1[-7:-4]) * 0.001 + 0.9
            if t1 >= t2:
                break

            f,i = math.modf( t1 )
            s1 = "s%08x_%03d.jpg" % ( int(i),int(1000.0*f) )

        eventFile.close()

        return True

    def ShowReplayArchive( self, widget ):
	self.replayArchiveDialog = self.wTree.get_widget("dialog3")
        self.replayArchiveDialog.show()
        return True

    def HideReplayArchive( self, widget ):
        self.replayArchiveDialog.hide()
	self.replayArchiveDialog = None
        return True

    def DeleteReplayArchive( self, widget, data ):
        self.replayArchiveDialog.hide()
        return True

    def TriggersAllowed( self ):
        t = time.time()
        now = time.localtime( t )
        timeofday = datetime.time( now.tm_hour, now.tm_min, now.tm_sec )
        if timeofday > self.disable_time and timeofday < self.enable_time:
            return False
	    
        self.recent_events = [ event for event in self.recent_events
                               if os.path.exists(event) and
                               (time.time() - os.path.getmtime(event)) < 3600.0 ]

        if len(self.recent_events) >= self.hourly_rate:
	    very_recent = [ event for event in self.recent_events
		            if (t - os.path.getmtime(event)) < (3600.0/self.hourly_rate) ]
	    if len(very_recent) >= 1:
                return False

        return True

    def RegisterUsage( self, name ):
        path = os.path.join( os.environ.get("HOME"), "images" )
        if not os.path.exists( path ):
            return

        path = os.path.join( path, name[:-12] )
        if not os.path.exists( path ):
            return

        path = os.path.join( path, name[:-10] )
        if not os.path.exists( path ):
            return

        name = os.path.splitext(name)[0]
        path = os.path.join( path, "a" + name[1:] + ".txt" )
        usage = 0
        if os.path.exists( path ):
            f = file( path, "r" )
            usage = int(f.readline())
            f.close()
        usage += 1
        f = file( path, "w" )
        f.write( "%d\n" % usage )
        f.close()

    def UnregisterUsage( self, name ):
        path = os.path.join( os.environ.get("HOME"), "images" )
        if not os.path.exists( path ):
            return

        path = os.path.join( path, name[:-12] )
        if not os.path.exists( path ):
            return

        path = os.path.join( path, name[:-10] )
        if not os.path.exists( path ):
            return

        name = os.path.splitext(name)[0]
        path = os.path.join( path, "a" + name[1:] + ".txt" )
        if not os.path.exists( path ):
            return

        f = file( path, "r" )
        usage = int(f.readline())
        f.close()

        usage = usage - 1
        if usage <= 0:
            os.remove( path )
        else:
            f = file( path, "w" )
            f.write( "%d\n" % usage )
            f.close()

    def StartEvent( self, name, count ):
        seconds = int(name[1:-4],16)
        msecs   = int(name[-3:])
        msecs += count * 33
        seconds += msecs // 1000
        msecs %= 1000
        eventName = "s%08x_%03d.txt" % (seconds,msecs)
        path = os.path.join( os.environ.get("HOME"), "events" )
        path = os.path.join( path, eventName )
        imageFile = "%s.jpg" % self.previous

        self.eventFile = file( path, "w" )
        self.eventFile.write( "%s\n" % imageFile )
        self.RegisterUsage( imageFile )
        self.recent_events.append( path )
 
    def CheckForTrigger( self, items ):
        if not self.triggered and self.eventFile != None:
            imageFile = "%s.jpg" % items[0]
            self.eventFile.write( "%s\n" % imageFile )
            self.RegisterUsage( imageFile )
            self.eventFile.close()
            self.eventFile = None
        elif not self.triggered and not self.TriggersAllowed():
            return
        elif len(items) > 2:
            triggered    = self.triggered
            triggerCount = self.triggerCount

            trigger_sum_begin   = int(self.settings["trigger_sum_begin"])
            trigger_count_begin = int(self.settings["trigger_count_begin"])
            trigger_sum_end     = int(self.settings["trigger_sum_end"])
            trigger_count_end   = int(self.settings["trigger_count_end"])

            counts = [ int(n,16) for n in items[1:] ]
            for i in range(len(counts)):
                n = counts[i]
                if triggered:
                    if n < trigger_sum_end:
                        trigger_count += 1
                    else:
                        trigger_count = 0
                    if trigger_count >= trigger_count_end:
                        triggered = False
                        trigger_count = 0
                else:
                    if n >= trigger_sum_begin:
                        trigger_count += 1
                    else:
                        trigger_count = 0
                    if trigger_count >= trigger_count_begin:
                        triggered = True
                        trigger_count = 0
                        self.StartEvent( items[0], i )
 
            self.triggered    = triggered
            self.triggerCount = triggerCount
        else:
            self.triggerCount = 0
            if self.triggered:
                self.triggered = False

        if self.eventFile != None:
            imageFile = "%s.jpg" % items[0]
            self.eventFile.write( "%s\n" % imageFile )
            self.RegisterUsage( imageFile )

        self.previous = items[0] 

    def GetEventSettings( self ):
        self.settings = { "site"                : "01",
	                  "name"                : "Sentinel",
			  "lat"                 : "0.0",
			  "lon"                 : "0.0",
			  "elv"                 : "0.0",
	                  "threshold"           : "30",
	                  "trigger_gap"         : "10",
			  "trigger_sum_begin"   : "12",
			  "trigger_sum_end"     : "5",
			  "trigger_count_begin" : "2",
			  "trigger_count_end"   : "3",
			  "trigger_pad_begin"   : "30",
			  "trigger_pad_end"     : "30" }

        try:			  
            f = file( os.path.join( os.environ.get("HOME"), "sentinel.conf" ) )
	    lines = f.readlines()
	    for l in lines:
	        items = l.split()
	        if len(items) >= 2:
	            self.settings[items[0]] = items[1]
	    f.close()
		    
	except:
	    pass
	
	home = os.getcwd()
	    
	f = file( os.path.join( os.environ.get("HOME"), "sentinel.conf" ), "w" )
	for key,value in self.settings.items():
	    if key != "ok":
	        f.write( "%s %s\n" % (key,value) )
	f.close()
	
        path = os.path.join( os.environ.get("HOME"), "events" )
	if not os.path.exists(path):
	    os.mkdir(path)

	if not os.path.exists("mask.dat"):
            s = chr(50) * (640*480)
            f = file("mask.dat", "wb")
            f.write(s)
	    	    

    def startButton_toggled(self, widget):
        if widget.get_active():
 	    widget.set_label("Stop")
            gap = self.settings["trigger_gap"]
            threshold = self.settings["threshold"]
            args = [ "./csentinel", threshold, gap ]
            self.csentinel = Popen( args, bufsize=-1, shell=False, stdout=PIPE )
 	    self.periodic = gobject.timeout_add( 200, self.Periodic)
	else:
	    widget.set_label("Begin")
	    gobject.source_remove( self.periodic )
            os.kill( self.csentinel.pid, signal.SIGTERM )
	    self.periodic = None
            self.csentinel = None
	
    def ShowEventSettings(self, widget):
        self.wTree.get_widget("evententry1").set_text( self.settings["site"] )
	self.wTree.get_widget("evententry2").set_text( self.settings["threshold"] )
	self.wTree.get_widget("evententry3").set_text( self.settings["trigger_gap"] )
	self.wTree.get_widget("evententry4").set_text( self.settings["trigger_sum_begin"] )
	self.wTree.get_widget("evententry5").set_text( self.settings["trigger_sum_end"] )
	self.wTree.get_widget("evententry6").set_text( self.settings["trigger_count_begin"] )
	self.wTree.get_widget("evententry7").set_text( self.settings["trigger_count_end"] )
	self.wTree.get_widget("evententry8").set_text( self.settings["trigger_pad_begin"] )
	self.wTree.get_widget("evententry9").set_text( self.settings["trigger_pad_end"] )
	
	self.wTree.get_widget("evententry10").set_text( self.settings["name"] )
	self.wTree.get_widget("evententry11").set_text( self.settings["lat"] )
	self.wTree.get_widget("evententry12").set_text( self.settings["lon"] )
	self.wTree.get_widget("evententry13").set_text( self.settings["elv"] )
        self.eventDialog.show()
	return True
	
    def DeleteEventSettings(self, widget, data ):
        self.eventDialog.hide()
	return True
	
    def CancelEventSettings(self, widget):
        self.eventDialog.hide()
	return True
	
    def OK_EventSettings(self, widget ):
        self.settings["site"]                = self.wTree.get_widget("evententry1").get_text()
        self.settings["threshold"]           = self.wTree.get_widget("evententry2").get_text()
        self.settings["trigger_gap"]         = self.wTree.get_widget("evententry3").get_text()
        self.settings["trigger_sum_begin"]   = self.wTree.get_widget("evententry4").get_text()
        self.settings["trigger_sum_end"]     = self.wTree.get_widget("evententry5").get_text()
        self.settings["trigger_count_begin"] = self.wTree.get_widget("evententry6").get_text()
        self.settings["trigger_count_end"]   = self.wTree.get_widget("evententry7").get_text()
        self.settings["trigger_pad_begin"]   = self.wTree.get_widget("evententry8").get_text()
        self.settings["trigger_pad_end"]     = self.wTree.get_widget("evententry9").get_text()

        self.settings["name"]                = self.wTree.get_widget("evententry10").get_text()
        self.settings["lat"]                 = self.wTree.get_widget("evententry11").get_text()
        self.settings["lon"]                 = self.wTree.get_widget("evententry12").get_text()
        self.settings["elv"]                 = self.wTree.get_widget("evententry13").get_text()
	
	f = file( "sentinel.conf", "w" )
	for key,value in self.settings.items():
	    if key != "ok":
	        f.write( "%s %s\n" % (key,value) )
	
        self.eventDialog.hide()
	return True

    def ShowDisplaySettings(self, widget):
        self.wTree.get_widget("displayentry1").set_text( "%d" % self.slowdown )
	self.wTree.get_widget("displayentry2").set_text( "%d" % self.hourly_rate )
	self.wTree.get_widget("displayentry3").set_text( self.disable_time.strftime("%H:%M:%S"))
	self.wTree.get_widget("displayentry4").set_text( self.enable_time.strftime("%H:%M:%S"))
	
	radio1 = self.wTree.get_widget("radiobutton1")
	radio2 = self.wTree.get_widget("radiobutton2")
	
	if self.gray_scale:
	    radio1.set_active( True )
	else:
	    radio2.set_active( True )
	    
	self.displayDialog.show()
	return True
	
    def CancelDisplaySettings(self,widget):
        self.displayDialog.hide()
	return True
	
    def ApplyDisplaySettings(self,widget):
        self.slowdown    = int(self.wTree.get_widget("displayentry1").get_text())
	self.hourly_rate = int(self.wTree.get_widget("displayentry2").get_text())
	s = self.wTree.get_widget("displayentry3").get_text()
        d = [ int(x) for x in s.split(":") ]
        self.enable_time = datetime.time(d[0],d[1],d[2])
	s = self.wTree.get_widget("displayentry4").get_text()
        d = [ int(x) for x in s.split(":") ]
        self.enable_time = datetime.time(d[0],d[1],d[2])
	
	self.gray_scale = self.wTree.get_widget("radiobutton1").get_active()
	
        return True

    def OK_DisplaySettings(self, widget):
        self.displayDialog.hide()
	return self.ApplyDisplaySettings(widget)
	
    def DeleteDisplaySettings(self, widget, data ):
        self.displayDialog.hide()
	return True
	
    def file_ok_sel(self, widget):
        current_path = self.filesel.get_filename()
        self.filesel.destroy()
	if current_path:
	    self.Read( current_path )
	   
    def Read( self, path ):
        base = os.path.basename( path )
	tv_sec = int(base[1:-8],16) + int(base[-7:-4])*0.001
	tstring = self.TimeFormat( tv_sec, True )
	lbl = self.wTree.get_widget("MainLabel")
	lbl.set_text( tstring )
	self.current_path = path
	self.NewReplay( None )

    def openEvent(self, widget):
        dialog = gtk.FileChooserDialog( title = "Event File",
	                                action = gtk.FILE_CHOOSER_ACTION_OPEN,
					buttons = ( gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
					            gtk.STOCK_OPEN, gtk.RESPONSE_OK ) )
	dialog.set_default_response( gtk.RESPONSE_OK )
	
	filter1 = gtk.FileFilter()
	filter1.set_name("Sentinel Event")
	filter1.add_pattern("s*.txt")
	dialog.add_filter( filter1 )
	
	filter2 = gtk.FileFilter()
	filter2.set_name("Image Files")
	filter2.add_pattern("*.jpg")
	filter2.add_pattern("*.tif")
	filter2.add_pattern("*.gif")
	filter2.add_pattern("*.png")
        filter2.add_pattern("*.pgm")
	dialog.add_filter( filter2 )
	
	response = dialog.run()
	if response == gtk.RESPONSE_OK:
	    current_path = dialog.get_filename()
	    if current_path:
	        ext = os.path.splitext(current_path)[1]
		if ext == ".txt":
	            self.Read( current_path )
		else:
		    self.ReadImage( current_path )
        dialog.destroy()

    def ReadImage( self, path ):
        try:
            img = Image.open( path )
	    if img.size != (640,480):
	        img = img.resize( (640,480) )
            self.raw_image = img
            img = self.raw_image.convert("RGB")
	    s = img.tostring()
	    pixbuf = gtk.gdk.pixbuf_new_from_data( s, gtk.gdk.COLORSPACE_RGB, 
	                                           False, 8, 640, 480, 640*3 )
	    self.img.set_from_pixbuf( pixbuf )
	except:
	    return
	
    def SaveJPEG(self, widget):
        if not self.raw_image:
	    return
	
	if not self.current_path:
	    base = "image"
	else:
	    base = os.path.basename(self.current_path)
	    base = os.path.splitext(base)[0]
	    
	name = base + ".jpg"
	
        dialog = gtk.FileChooserDialog(title="Save as JPEG",
	                               action=gtk.FILE_CHOOSER_ACTION_SAVE,
	                               buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
				       gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
	dialog.set_current_name(name)
	response = dialog.run()
	if response == gtk.RESPONSE_OK:
	    path = dialog.get_filename()
	    img = self.raw_image.convert("RGB")
	    img.save(path)
	dialog.destroy()

    def SaveMaskPGM(self, widget ):
        if not self.raw_image:
            return

        path = os.path.join( os.environ.get("HOME"), "mask.pgm" )
        img = self.raw_image.convert("L")
        img.save( path )
	
    def SaveTIFF(self, widget):
        if not self.raw_image:
	    return
	
	if not self.current_path:
	    base = "image"
	else:
	    base = os.path.basename(self.current_path)
	    base = os.path.splitext(base)[0]
	    
	name = base + ".tif"
	
        dialog = gtk.FileChooserDialog(title="Save as TIFF",
	                               action=gtk.FILE_CHOOSER_ACTION_SAVE,
	                               buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
				       gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
	dialog.set_current_name(name)
	response = dialog.run()
	if response == gtk.RESPONSE_OK:
	    path = dialog.get_filename()
	    self.raw_image.save(path)
	dialog.destroy()
	
    def SaveMovie(self, widget):
        if not self.current_path:
	    return
	    
        dialog = gtk.FileChooserDialog(title="Save Movie",
	                               action=gtk.FILE_CHOOSER_ACTION_SAVE,
	                               buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
				       gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
	
	base = os.path.basename(self.current_path)
	base = os.path.splitext(base)[0]
	name = base + ".mpeg"
	dialog.set_current_name(name)
		
	response = dialog.run()
	if response == gtk.RESPONSE_OK:
	    path = dialog.get_filename()
	    self.SEV_MakeMovie( path )
	dialog.destroy()

    def SaveTimeHistory( self, widget ):
        if not self.current_path:
	    return
	    
        dialog = gtk.FileChooserDialog(title="Save Time History",
	                               action=gtk.FILE_CHOOSER_ACTION_SAVE,
	                               buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,
				       gtk.STOCK_SAVE,gtk.RESPONSE_OK))
        dialog.set_default_response(gtk.RESPONSE_OK)
	
	base = os.path.basename(self.current_path)
	base = os.path.splitext(base)[0]
	name = base + ".txt"
	dialog.set_current_name(name)
		
	response = dialog.run()
	if response == gtk.RESPONSE_OK:
	    path = dialog.get_filename()
	    self.MakeTimeHistory( path )
	dialog.destroy()

        
    def SEV_MakeMovie( self, path ):
        if self.event_jpeg_file:
           os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
           self.event_jpeg_file = None
           self.frame_index = 0

	if self.timeout:
	    gobject.source_remove( self.timeout )
	    self.timeout = None

        if not self.current_path:
            return

        event_text_file = file( self.current_path, "r" )
        if not event_text_file:
            return

        event_play_list = event_text_file.readlines()
        if not event_play_list:
            return
        event_text_file.close()

        cmd = "mpeg2enc -a 1 -f 0 -I 0 -q 7 -b 3000 -M 0 -V 512 -v 0 -F 4 -n n -o %s" % path

        p = os.popen( cmd, "w" )
        chroma = "\x80" * (640 * 480 / 2)

        p.write( "YUV4MPEG2 W640 H480 C420mpeg2 Ip\n" )
	
        for txt in event_play_list:
            path = self.ImagePath( txt )
	    if not os.path.exists(path):
	        return
      
            args = [ "/usr/bin/djpeg", "-grayscale", "-pnm", path ]
            event_jpeg_file = Popen( args, bufsize=-1, shell=False, stdout=PIPE )
            magic = event_jpeg_file.stdout.read(17)
            if magic != "P5\n640 14400\n255\n":
                os.kill( event_jpeg_file.pid, signal.SIGTERM )
                return

            for i in range(30):
                p.write( "FRAME\n" )           
                s = event_jpeg_file.stdout.read( 640*480 )
                if not self.gray_scale:
                    img = Image.new( "P", (640,480) )
                    img.putdata( s )
                    img.putpalette(self.palette)
                    img = img.convert( "YCbCr" )
                    y,cb,cr = img.split()
                    p.write( y.tostring() )
                    cb = cb.resize( (320,240) )
                    cr = cr.resize( (320,240) )
                    p.write( cb.tostring() )
                    p.write( cr.tostring() )
                else:
                    p.write(s)
                    p.write(chroma)

            event_jpeg_file.wait()

        p.close()    

    def MakeTimeHistory( self, path ):
        if self.event_jpeg_file:
           os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
           self.event_jpeg_file = None
           self.frame_index = 0

	if self.timeout:
	    gobject.source_remove( self.timeout )
	    self.timeout = None

        if not self.current_path:
            return

        event_text_file = file( self.current_path, "r" )
        if not event_text_file:
            return

        event_play_list = event_text_file.readlines()
        if not event_play_list:
            return
        event_text_file.close()

        th_file = file( path, "w" )
        if not th_file:
            return

        for txt in event_play_list:
            path = self.ImagePath( txt )
	    if not os.path.exists(path):
	        return
      
            args = [ "/usr/bin/djpeg", "-grayscale", "-pnm", path ]
            event_jpeg_file = Popen( args, bufsize=-1, shell=False, stdout=PIPE )
            magic = event_jpeg_file.stdout.read(17)
            if magic != "P5\n640 14400\n255\n":
                os.kill( event_jpeg_file.pid, signal.SIGTERM )
                return

            for i in range(30):
                s = event_jpeg_file.stdout.read( 640*480 )
                img = Image.new( "P", (640,480) )
                img.putdata( s )

                for upper in range( 0, 480, 120 ):
                    for left in range( 0, 640, 160 ):
                        crop = img.crop( (left, upper, left+160, upper+120) )
                        cdata = crop.getdata()
                        csum = 0
                        for datum in cdata:
                            csum += datum
                        th_file.write( "%d " % csum )
                th_file.write( "\n" )

            event_jpeg_file.wait()

        th_file.close()    

    def ImagePath( self, name ):
        name = name.strip() 
        path = os.path.join( os.environ.get("HOME"), "images" )
        path = os.path.join( path, name[:-12] )
        path = os.path.join( path, name[:-10] )
        path = os.path.join( path, name )

        return path

    def PlayVCR_Next( self ):
        if not self.event_jpeg_file:
            if not self.vcr_file:
                return False

            path = self.vcr_file

            args = [ "/usr/bin/djpeg", "-grayscale", "-pnm", path ]
            self.event_jpeg_file = Popen( args, bufsize=-1, shell=False, stdout=PIPE )
            magic = self.event_jpeg_file.stdout.read(17)
            if magic != "P5\n640 14400\n255\n":
                os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
                self.event_jpef_file = None
                self.frame_index = 0
                return False

        if self.vcr_fast:
            s = self.event_jpeg_file.stdout.read( 640*480*2 )
            self.frame_index += 2
   
        s = self.event_jpeg_file.stdout.read( 640*480 )
        self.frame_index += 1

	self.raw_image = Image.new( "P", (640,480) )
	self.raw_image.putdata( s )
        if not self.gray_scale:
            self.raw_image.putpalette(self.palette)
            
	img = self.raw_image.convert("RGB")
	
	s = img.tostring()
	pixbuf = gtk.gdk.pixbuf_new_from_data( s, gtk.gdk.COLORSPACE_RGB, 
	                                       False, 8, 640, 480, 640*3 )
	
	self.img.set_from_pixbuf( pixbuf )
       
	tstring = self.TimeFormat( self.vcr_time, True )
	lbl = self.wTree.get_widget("MainLabel")
	lbl.set_text( tstring )
	
	while gtk.events_pending():
	    gtk.main_iteration()

        self.vcr_time += 0.0333

        if self.vcr_fast:
            self.vcr_time += 0.0667

        if self.frame_index >= 30:
            self.event_jpeg_file.wait()
            self.event_jpeg_file = None
            self.frame_index = 0

            newtime = 0.001 * int(self.vcr_file[-7:-4]) + int(self.vcr_file[-16:-8],16) + 0.9
            f,i = math.modf( newtime )
            newname = "s%08x_%03d.jpg" % ( int(i),int(1000.0*f) )
            self.vcr_file = self.FindNearestStrip( newname )
            if self.vcr_file:
                self.vcr_time = int(self.vcr_file[-16:-8],16) + 0.001*int(self.vcr_file[-7:-4])
                delta = int(self.vcr_file[-16:-8],16) - self.vcr_start_time
                spinDuration = self.wTree.get_widget( "spinbuttonDuration" )
                spinDuration.set_value( delta )

        return True

    def NewReplayNext( self ):
        if not self.event_jpeg_file:
            if not self.event_play_list:
                return False

            txt = self.event_play_list.pop(0)
            if not txt:
                return False
            
            self.vcr_time = int(txt[1:9],16) + 0.001*int(txt[10:13])
            path = self.ImagePath( txt )
	    if not os.path.exists(path):
                print "No path: %s" % path
	        return False

            args = [ "/usr/bin/djpeg", "-grayscale", "-pnm", path ]
            self.event_jpeg_file = Popen( args, bufsize=-1, shell=False, stdout=PIPE )
            magic = self.event_jpeg_file.stdout.read(17)
            if magic != "P5\n640 14400\n255\n":
                os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
                self.event_jpef_file = None
                self.frame_index = 0
                return False

        s = self.event_jpeg_file.stdout.read( 640*480 )
        self.frame_index += 1

	self.raw_image = Image.new( "P", (640,480) )
	self.raw_image.putdata( s )
        if not self.gray_scale:
            self.raw_image.putpalette(self.palette)
            
	img = self.raw_image.convert("RGB")
	
	s = img.tostring()
	pixbuf = gtk.gdk.pixbuf_new_from_data( s, gtk.gdk.COLORSPACE_RGB, 
	                                       False, 8, 640, 480, 640*3 )
	
	self.img.set_from_pixbuf( pixbuf )

	tstring = self.TimeFormat( self.vcr_time, True )
	lbl = self.wTree.get_widget("MainLabel")
	lbl.set_text( tstring )

        self.vcr_time += 0.0333
	
	while gtk.events_pending():
	    gtk.main_iteration()

        if self.frame_index >= 30:
            self.event_jpeg_file.wait()
            self.event_jpeg_file = None
            self.frame_index = 0

        return True

    def NewReplay( self, widget ):
        if self.event_jpeg_file:
           os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
           self.event_jpeg_file = None
           self.frame_index = 0

	if self.timeout:
	    gobject.source_remove( self.timeout )
	    self.timeout = None

        if not self.current_path:
            return

        event_text_file = file( self.current_path, "r" )
        if not event_text_file:
            return

        self.event_play_list = event_text_file.readlines()
      
	self.timeout = gobject.timeout_add( 30*self.slowdown, self.NewReplayNext)

    def ShowComposite( self, widget ):
        if self.event_jpeg_file:
           os.kill( self.event_jpeg_file.pid, signal.SIGTERM )
           self.event_jpeg_file = None
           self.frame_index = 0

	if self.timeout:
	    gobject.source_remove( self.timeout )
	    self.timeout = None

        if not self.current_path:
            return

        event_text_file = file( self.current_path, "r" )
        if not event_text_file:
            return

        event_play_list = event_text_file.readlines()
        if not event_play_list:
            return
        event_text_file.close()

        self.raw_image = None

        for txt in event_play_list:
            path = self.ImagePath( txt )
	    if not os.path.exists(path):
	        return
      
            args = [ "/usr/bin/djpeg", "-grayscale", "-pnm", path ]
            event_jpeg_file = Popen( args, bufsize=-1, shell=False, stdout=PIPE )
            magic = event_jpeg_file.stdout.read(17)
            if magic != "P5\n640 14400\n255\n":
                os.kill( event_jpeg_file.pid, signal.SIGTERM )
                return

            for i in range(30):
                s = event_jpeg_file.stdout.read( 640*480 )
	        img2 = Image.new( "P", (640,480) )
	        img2.putdata( s )
                if self.raw_image == None:
                    self.raw_image = img2
                else:
	            self.raw_image = ImageChops.lighter(self.raw_image,img2)

            event_jpeg_file.wait()

	if not self.gray_scale:
	    self.raw_image.putpalette(self.palette)
	
	img = self.raw_image.convert("RGB")
	s = img.tostring()
	pixbuf = gtk.gdk.pixbuf_new_from_data( s, gtk.gdk.COLORSPACE_RGB, 
	                                       False, 8, 640, 480, 640*3 )
	self.img.set_from_pixbuf( pixbuf )
        

    def PlayFirst( self, widget ):
        paths = glob.glob(GLOB_STRING)
        if not paths:
            return
        paths.sort()
        self.Read( paths[0] )

    def PlayLast( self, widget ):
        paths = glob.glob(GLOB_STRING)
        if not paths:
            return
        paths.sort()
        self.Read( paths[-1] )
        
    def PlayNext( self, widget ):
        paths = glob.glob(GLOB_STRING)
        if not paths:
            return
        paths.sort()
        if not self.current_path:
            self.Read( paths[0] )
        else:
            i = bisect.bisect( paths, self.current_path )
            if i >= len(paths):
	        if self.timeout:
	            gobject.source_remove( self.timeout )
	            self.timeout = None
	        lbl = self.wTree.get_widget("MainLabel")
	        lbl.set_text( "End of list reached." )
		self.img.set_from_file("wagon.tif")
                self.current_path = None
                return
            
            self.Read( paths[i] )

    def PlayPrevious( self, widget ):
        paths = glob.glob(GLOB_STRING)
        if not paths:
            return
        paths.sort()
        if not self.current_path:
            self.Read( paths[-1] )
        else:
            i = bisect.bisect( paths, self.current_path )
            if i <= 1:
	        if self.timeout:
	            gobject.source_remove( self.timeout )
	            self.timeout = None
	        lbl = self.wTree.get_widget("MainLabel")
	        lbl.set_text( "End of list reached." )
		self.img.set_from_file("wagon.tif")
                self.current_path = None
                return
            
            self.Read( paths[i-2] )

    def Delete( self, widget ):
        if not self.current_path:
            return
        xpath = self.current_path
        self.PlayNext(widget)

        f = file( xpath, "r" )
        for line in f.readlines():
            line = line.strip()
            self.UnregisterUsage( line )

        os.remove( xpath )

    def Periodic( self ):
        speakers = [ self.csentinel.stdout ]
        speaking = select.select( speakers, [], [], 0 )[0]
        if len(speaking) > 0:
            t = self.csentinel.stdout.readline()
            items = t.split()
            self.CheckForTrigger( items )

            if len(items) < 2:
                return True
            
            mysum = 0
            if len(items) > 2:
                mysum = sum( [ int(x,16) for x in items[1:] ] )
 	    lbl = self.wTree.get_widget("SubLabel")
            f = items[0]
            t = int(f[1:-4],16)
            s = self.TimeFormat( t, False )
	    lbl.set_text( "%s %6d" % (s, mysum) )

            if self.DiskUsage() > 90:
                self.DeleteEarliest()

        return True

if __name__ == "__main__":
    hwg = SentinelGTK()
    gtk.main()

