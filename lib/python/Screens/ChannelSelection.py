# -*- coding: utf-8 -*-
from Screens.Screen import Screen
from Screens.Setup import Setup
import Screens.InfoBar
from Screens.ScreenSaver import InfoBarScreenSaver
import Components.ParentalControl
from Components.Button import Button
from Components.Label import Label
from Components.Sources.Boolean import Boolean
from Components.Pixmap import Pixmap
from Components.ServiceList import ServiceList, ServiceListLegacy, refreshServiceList
from Components.ActionMap import NumberActionMap, ActionMap, HelpableActionMap, HelpableNumberActionMap
from Components.MenuList import MenuList
from Components.ServiceEventTracker import ServiceEventTracker, InfoBarBase
from ServiceReference import ServiceReference, getStreamRelayRef, serviceRefAppendPath, service_types_radio_ref, service_types_tv_ref
from enigma import eServiceReference, eServiceReferenceDVB, eEPGCache, eServiceCenter, eRCInput, eTimer, eDVBDB, iPlayableService, iServiceInformation, getPrevAsciiCode, loadPNG, eProfileWrite
eProfileWrite("ChannelSelection.py 1")
from Screens.EpgSelection import EPGSelection
from Components.config import config, configfile, ConfigSubsection, ConfigText, ConfigYesNo, ConfigSelection, ConfigText
from Tools.NumericalTextInput import NumericalTextInput
eProfileWrite("ChannelSelection.py 2")
from Components.NimManager import nimmanager
eProfileWrite("ChannelSelection.py 2.1")
from Components.Sources.RdsDecoder import RdsDecoder
eProfileWrite("ChannelSelection.py 2.2")
from Components.Sources.ServiceEvent import ServiceEvent
from Components.Sources.Event import Event
eProfileWrite("ChannelSelection.py 2.3")
from Components.Input import Input
eProfileWrite("ChannelSelection.py 3")
from Components.ChoiceList import ChoiceList, ChoiceEntryComponent
from Components.SystemInfo import BoxInfo
from Components.Sources.StaticText import StaticText
from Screens.InputBox import PinInput
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Screens.MessageBox import MessageBox
from Screens.ServiceInfo import ServiceInfo
from Screens.Hotkey import InfoBarHotkey, hotkeyActionMap, hotkey
eProfileWrite("ChannelSelection.py 4")
from Screens.PictureInPicture import PictureInPicture
from Screens.RdsDisplay import RassInteractive
from Tools.BoundFunction import boundFunction
from Tools.Notifications import RemovePopup
from Tools.Alternatives import GetWithAlternative, CompareWithAlternatives
from Tools.Directories import fileExists, resolveFilename, sanitizeFilename, SCOPE_PLUGINS
from Plugins.Plugin import PluginDescriptor
from Components.PluginComponent import plugins
from Screens.ChoiceBox import ChoiceBox
from Screens.EventView import EventViewEPGSelect
from Screens.Setup import Setup
import os
from time import time, localtime, strftime
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.Renderer.Picon import getPiconName
eProfileWrite("ChannelSelection.py after imports")

FLAG_SERVICE_NEW_FOUND = 64
FLAG_IS_DEDICATED_3D = 128
FLAG_CENTER_DVB_SUBS = 2048 #define in lib/dvb/idvb.h as dxNewFound = 64 and dxIsDedicated3D = 128
FLAG_NO_AI_TRANSLATION = 8192


class InsertService(Setup):
	def __init__(self, session):
		self.createConfig()
		Setup.__init__(self, session, None)

	def createConfig(self):
		choices = [("Select Service", _("Select Service"))]
		if BoxInfo.getItem("HasHDMIin"):
			choices.append(("HDMI-in", _("HDMI-In")))
		choices.append(("IPTV stream", _("Enter URL")))
		self.servicetype = ConfigSelection(choices=choices)
		self.streamtype = ConfigSelection(["1", "4097", "5001", "5002"])
		self.streamurl = ConfigText("http://some_url_to_stream")
		self.servicename = ConfigText("default_name")

	def createSetup(self):
		if self.servicetype.value == "HDMI-in":
			self.servicerefstring = '8192:0:1:0:0:0:0:0:0:0::%s' % self.servicename.value
		else:
			self.servicerefstring = '%s:0:1:0:0:0:0:0:0:0:%s:%s' % (self.streamtype.value, self.streamurl.value.replace(':', '%3a'), self.servicename.value)
		self.title = '%s [%s]' % (_("Insert Service"), self.servicerefstring)
		self.list = []
		self.list.append((_("Service Type"), self.servicetype, _("Select service type")))
		if self.servicetype.value != "Select Service":
			if self.servicetype.value != "HDMI-in":
				self.list.append((_("Stream Type"), self.streamtype, _("Select stream type")))
				self.list.append((_("Stream URL"), self.streamurl, _("Select stream URL")))
			self.list.append((_("Service Name"), self.servicename, _("Select service name")))
		self["config"].list = self.list

	def changedEntry(self):
		self.createSetup()

	def keySave(self):
		if self.servicetype.value == "Select Service":
			self.session.openWithCallback(self.channelSelectionCallback, SimpleChannelSelection, _("Select channel"))
		else:
			self.close(eServiceReference(self.servicerefstring))

	def keySelect(self):
		self.keySave()

	def channelSelectionCallback(self, *args):
		if len(args):
			self.close(args[0])


class BouquetSelector(Screen):
	def __init__(self, session, bouquets, selectedFunc, enableWrapAround=True):
		Screen.__init__(self, session)
		self.setTitle(_("Choose bouquet"))

		self.selectedFunc = selectedFunc

		self["actions"] = ActionMap(["OkCancelActions"],
			{
				"ok": self.okbuttonClick,
				"cancel": self.cancelClick
			})
		entrys = [(x[0], x[1]) for x in bouquets]
		self["menu"] = MenuList(entrys, enableWrapAround)

	def getCurrent(self):
		cur = self["menu"].getCurrent()
		return cur and cur[1]

	def okbuttonClick(self):
		self.selectedFunc(self.getCurrent())

	def up(self):
		self["menu"].up()

	def down(self):
		self["menu"].down()

	def cancelClick(self):
		self.close(False)


class SilentBouquetSelector:
	def __init__(self, bouquets, enableWrapAround=False, current=0):
		self.bouquets = [b[1] for b in bouquets]
		self.pos = current
		self.count = len(bouquets)
		self.enableWrapAround = enableWrapAround

	def up(self):
		if self.pos > 0 or self.enableWrapAround:
			self.pos = (self.pos - 1) % self.count

	def down(self):
		if self.pos < (self.count - 1) or self.enableWrapAround:
			self.pos = (self.pos + 1) % self.count

	def getCurrent(self):
		return self.bouquets[self.pos]


# csel.bouquet_mark_edit values
OFF = 0
EDIT_BOUQUET = 1
EDIT_ALTERNATIVES = 2


def append_when_current_valid(current, menu, args, level=0, key="dummy"):
	if current and current.valid() and level <= config.usage.setup_level.index:
		menu.append(ChoiceEntryComponent(key, args))


def removed_userbouquets_available():
	for file in os.listdir("/etc/enigma2/"):
		if file.startswith("userbouquet") and file.endswith(".del"):
			return True
	return False


class ChannelContextMenu(Screen):
	def __init__(self, session, csel):

		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("Channel context menu"))
		self.csel = csel
		self.bsel = None
		if self.isProtected():
			self.onFirstExecBegin.append(boundFunction(self.session.openWithCallback, self.protectResult, PinInput, pinList=[x.value for x in config.ParentalControl.servicepin], triesEntry=config.ParentalControl.retries.servicepin, title=_("Please enter the correct PIN code"), windowTitle=_("Enter PIN code")))

		self["actions"] = ActionMap(["OkCancelActions", "ColorActions", "NumberActions", "MenuActions"],
			{
				"ok": self.okbuttonClick,
				"cancel": self.cancelClick,
				"blue": self.showServiceInPiP,
				"red": self.playMain,
				"menu": self.openSetup,
				"1": self.unhideParentalServices,
				"2": self.renameEntry,
				"3": self.findCurrentlyPlayed,
				"4": self.showSubservices,
				"5": self.insertEntry,
				"6": self.addServiceToBouquetOrAlternative,
				"7": self.toggleMoveModeSelect,
				"8": self.removeEntry
			})
		menu = []

		self.removeFunction = False
		self.addFunction = False
		self.PiPAvailable = False
		current = csel.getCurrentSelection()
		current_root = csel.getRoot()
		current_sel_path = current.getPath()
		current_sel_flags = current.flags
		self.inBouquetRootList = current_root and 'FROM BOUQUET "bouquets.' in current_root.getPath() #FIXME HACK
		inAlternativeList = current_root and 'FROM BOUQUET "alternatives' in current_root.getPath()
		self.inBouquet = csel.getMutableList() is not None
		haveBouquets = config.usage.multibouquet.value
		self.subservices = csel.getSubservices(current)
		from Components.ParentalControl import parentalControl
		self.parentalControl = parentalControl
		self.parentalControlEnabled = config.ParentalControl.servicepin[0].value and config.ParentalControl.servicepinactive.value
		if not (current_sel_path or current_sel_flags & (eServiceReference.isDirectory | eServiceReference.isMarker)) or current_sel_flags & eServiceReference.isGroup:
			append_when_current_valid(current, menu, (_("Show transponder info"), self.showServiceInformations), level=2)
		if self.subservices and not csel.isSubservices():
			appendWhenValid(current, menu, (_("Show Subservices Of Active Service"), self.showSubservices), key="4")
		if csel.bouquet_mark_edit == OFF and not csel.entry_marked:
			if not self.inBouquetRootList:
				isPlayable = not (current_sel_flags & (eServiceReference.isMarker | eServiceReference.isDirectory))
				if isPlayable:
					for p in plugins.getPlugins(PluginDescriptor.WHERE_CHANNEL_CONTEXT_MENU):
						append_when_current_valid(current, menu, (p.name, boundFunction(self.runPlugin, p)), key="bullet")
					if config.servicelist.startupservice.value == current.toString():
						append_when_current_valid(current, menu, (_("Stop using as startup service"), self.unsetStartupService), level=0)
					else:
						append_when_current_valid(current, menu, (_("Set as startup service"), self.setStartupService), level=0)
					if self.parentalControlEnabled:
						if self.parentalControl.getProtectionLevel(current.toCompareString()) == -1:
							append_when_current_valid(current, menu, (_("Add to parental protection"), boundFunction(self.addParentalProtection, current)), level=0)
						else:
							if self.parentalControl.isServiceProtectionBouquet(current.toCompareString()):
								append_when_current_valid(current, menu, (_("Service belongs to a parental protected bouquet"), self.cancelClick), level=0)
							else:
								append_when_current_valid(current, menu, (_("Remove from parental protection"), boundFunction(self.removeParentalProtection, current)), level=0)
						if self.parentalControl.blacklist and config.ParentalControl.hideBlacklist.value and not self.parentalControl.sessionPinCached and config.ParentalControl.storeservicepin.value != "never":
							append_when_current_valid(current, menu, (_("Unhide parental control services"), self.unhideParentalServices), level=0, key="1")
					if BoxInfo.getItem("3DMode") and fileExists(resolveFilename(SCOPE_PLUGINS, "SystemPlugins/OSD3DSetup/plugin.pyc")):
						if eDVBDB.getInstance().getFlag(eServiceReference(current.toString())) & FLAG_IS_DEDICATED_3D:
							append_when_current_valid(current, menu, (_("Unmark service as dedicated 3D service"), self.removeDedicated3DFlag), level=2)
						else:
							append_when_current_valid(current, menu, (_("Mark service as dedicated 3D service"), self.addDedicated3DFlag), level=2)
					if not (current_sel_path):
						if Screens.InfoBar.InfoBar.instance.checkHideVBI(current):
							append_when_current_valid(current, menu, (_("Uncover dashed flickering line for this service"), self.toggleVBI), level=1)
						else:
							append_when_current_valid(current, menu, (_("Cover dashed flickering line for this service"), self.toggleVBI), level=1)
						if Screens.InfoBar.InfoBar.instance.checkStreamrelay(current):
							append_when_current_valid(current, menu, (_("Play service without Stream Relay"), self.toggleStreamrelay), level=1)
						else:
							append_when_current_valid(current, menu, (_("Play service with Stream Relay"), self.toggleStreamrelay), level=1)
						if eDVBDB.getInstance().getCachedPid(eServiceReference(current.toString()), 9) >> 16 not in (-1, eDVBDB.getInstance().getCachedPid(eServiceReference(current.toString()), 2)):
							#Only show when a DVB subtitle is cached on this service
							if eDVBDB.getInstance().getFlag(eServiceReference(current.toString())) & FLAG_CENTER_DVB_SUBS:
								append_when_current_valid(current, menu, (_("Do not center DVB subs on this service"), self.removeCenterDVBSubsFlag), level=2)
							else:
								append_when_current_valid(current, menu, (_("Do center DVB subs on this service"), self.addCenterDVBSubsFlag), level=2)
					if BoxInfo.getItem("AISubs"):
						if eDVBDB.getInstance().getFlag(eServiceReference(current.toString())) & FLAG_NO_AI_TRANSLATION:
							appendWhenValid(current, menu, (_("Translate Subs On This Service"), self.removeNoAITranslationFlag))
						else:
							appendWhenValid(current, menu, (_("Don't Translate Subs On This Service"), self.addNoAITranslationFlag))
					if not csel.isSubservices():
						if haveBouquets:
							bouquets = self.csel.getBouquetList()
							if bouquets is None:
								bouquetCnt = 0
							else:
								bouquetCnt = len(bouquets)
							if not self.inBouquet or bouquetCnt > 1:
								append_when_current_valid(current, menu, (_("Add service to bouquet"), self.addServiceToBouquetSelected), level=0, key="5")
								self.addFunction = self.addServiceToBouquetSelected
							if not self.inBouquet:
								append_when_current_valid(current, menu, (_("Remove entry"), self.removeEntry), level=0, key="8")
								self.removeFunction = self.removeSatelliteService
						else:
							if not self.inBouquet:
								append_when_current_valid(current, menu, (_("Add service to favourites"), self.addServiceToBouquetSelected), level=0, key="5")
								self.addFunction = self.addServiceToBouquetSelected
					if BoxInfo.getItem("PIPAvailable"):
						self.PiPAvailable = True
						if self.csel.dopipzap:
							append_when_current_valid(current, menu, (_("Play in main window"), self.playMain), level=0, key="red")
						else:
							append_when_current_valid(current, menu, (_("Play as Picture in Picture"), self.showServiceInPiP), level=0, key="blue")
					append_when_current_valid(current, menu, (_("Find currently playing service"), self.findCurrentlyPlayed), level=0, key="3")
				else:
					if 'FROM SATELLITES' in current_root.getPath() and current and _("Services") in eServiceCenter.getInstance().info(current).getName(current):
						unsigned_orbpos = current.getUnsignedData(4) >> 16
						if unsigned_orbpos == 0xFFFF:
							append_when_current_valid(current, menu, (_("Remove cable services"), self.removeSatelliteServices), level=0)
						elif unsigned_orbpos == 0xEEEE:
							append_when_current_valid(current, menu, (_("Remove terrestrial services"), self.removeSatelliteServices), level=0)
						else:
							append_when_current_valid(current, menu, (_("Remove selected satellite"), self.removeSatelliteServices), level=0)
					if haveBouquets:
						if not self.inBouquet and not "PROVIDERS" in current_sel_path:
							append_when_current_valid(current, menu, (_("Copy to bouquets"), self.copyCurrentToBouquetList), level=0)
							append_when_current_valid(current, menu, (_("Copy To Stream Relay"), self.copyCurrentToStreamRelay), level=0)
					if ("flags == %d" % (FLAG_SERVICE_NEW_FOUND)) in current_sel_path:
						append_when_current_valid(current, menu, (_("Remove all new found flags"), self.removeAllNewFoundFlags), level=0)
				if self.inBouquet:
					append_when_current_valid(current, menu, (_("Rename entry"), self.renameEntry), level=0, key="2")
					if not inAlternativeList:
						append_when_current_valid(current, menu, (_("Remove entry"), self.removeEntry), level=0, key="8")
						self.removeFunction = self.removeCurrentService
						if config.usage.setup_level.index >= 2:
							menu.append(ChoiceEntryComponent("4", (_("Insert entry"), self.insertService)))
				if current_root and ("flags == %d" % (FLAG_SERVICE_NEW_FOUND)) in current_root.getPath():
					append_when_current_valid(current, menu, (_("Remove new found flag"), self.removeNewFoundFlag), level=0)
			else:
				if self.parentalControlEnabled:
					if self.parentalControl.blacklist and config.ParentalControl.hideBlacklist.value and not self.parentalControl.sessionPinCached and config.ParentalControl.storeservicepin.value != "never":
						append_when_current_valid(current, menu, (_("Unhide parental control services"), self.unhideParentalServices), level=0, key="1")
					if self.parentalControl.getProtectionLevel(current.toCompareString()) == -1:
						append_when_current_valid(current, menu, (_("Add bouquet to parental protection"), boundFunction(self.addParentalProtection, current)), level=0)
					else:
						append_when_current_valid(current, menu, (_("Remove bouquet from parental protection"), boundFunction(self.removeParentalProtection, current)), level=0)
				menu.append(ChoiceEntryComponent("4", (_("Add bouquet"), self.showBouquetInputBox)))
				append_when_current_valid(current, menu, (_("Rename entry"), self.renameEntry), level=0, key="2")
				append_when_current_valid(current, menu, (_("Remove entry"), self.removeEntry), level=0, key="8")
				self.removeFunction = self.removeBouquet
				if removed_userbouquets_available():
					append_when_current_valid(current, menu, (_("Purge deleted user bouquets"), self.purgeDeletedBouquets), level=0)
					append_when_current_valid(current, menu, (_("Restore deleted user bouquets"), self.restoreDeletedBouquets), level=0)
				if Screens.InfoBar.InfoBar.instance.checkBouquets(current.toString().split('"')[1]):
					append_when_current_valid(current, menu, (_("Unpin Userbouquet"), self.toggleBouquet), level=2)
				else:
					append_when_current_valid(current, menu, (_("Pin Userbouquet"), self.toggleBouquet), level=2)
				append_when_current_valid(current, menu, (_("Reload services/bouquets list"), self.reloadServicesBouquets), level=2)
		if self.inBouquet: # current list is editable?
			if csel.bouquet_mark_edit == OFF:
				if csel.movemode:
					append_when_current_valid(current, menu, (_("Disable move mode"), self.toggleMoveMode), level=0, key="6")
				else:
					append_when_current_valid(current, menu, (_("Enable move mode"), self.toggleMoveMode), level=0, key="6")
				if csel.entry_marked and not inAlternativeList:
					append_when_current_valid(current, menu, (_("Remove entry"), self.removeEntry), level=0, key="8")
					self.removeFunction = self.removeCurrentService
				if not csel.entry_marked and not self.inBouquetRootList and current_root and not (current_root.flags & eServiceReference.isGroup):
					if current.type != -1:
						menu.append(ChoiceEntryComponent("dummy", (_("Add marker"), self.showMarkerInputBox)))
					if not csel.movemode:
						if haveBouquets:
							append_when_current_valid(current, menu, (_("Enable bouquet edit"), self.bouquetMarkStart), level=0)
						else:
							append_when_current_valid(current, menu, (_("Enable favourites edit"), self.bouquetMarkStart), level=0)
					if current_sel_flags & eServiceReference.isGroup:
						append_when_current_valid(current, menu, (_("Edit alternatives"), self.editAlternativeServices), level=2)
						append_when_current_valid(current, menu, (_("Show alternatives"), self.showAlternativeServices), level=2)
						append_when_current_valid(current, menu, (_("Remove all alternatives"), self.removeAlternativeServices), level=2)
					elif not current_sel_flags & eServiceReference.isMarker:
						append_when_current_valid(current, menu, (_("Add alternatives"), self.addAlternativeServices), level=2)
			else:
				if csel.bouquet_mark_edit == EDIT_BOUQUET:
					if haveBouquets:
						append_when_current_valid(current, menu, (_("End bouquet edit"), self.bouquetMarkEnd), level=0)
						append_when_current_valid(current, menu, (_("Abort bouquet edit"), self.bouquetMarkAbort), level=0)
					else:
						append_when_current_valid(current, menu, (_("End favourites edit"), self.bouquetMarkEnd), level=0)
						append_when_current_valid(current, menu, (_("Abort favourites edit"), self.bouquetMarkAbort), level=0)
					if current_sel_flags & eServiceReference.isMarker:
						append_when_current_valid(current, menu, (_("Rename entry"), self.renameEntry), level=0, key="2")
						append_when_current_valid(current, menu, (_("Remove entry"), self.removeEntry), level=0, key="8")
						self.removeFunction = self.removeCurrentService
				else:
					append_when_current_valid(current, menu, (_("End alternatives edit"), self.bouquetMarkEnd), level=0)
					append_when_current_valid(current, menu, (_("Abort alternatives edit"), self.bouquetMarkAbort), level=0)

		menu.append(ChoiceEntryComponent("menu", (_("Settings..."), self.openSetup)))
		self["menu"] = ChoiceList(menu)

	def insertEntry(self):
		if self.inBouquetRootList:
			self.showBouquetInputBox()
		else:
			self.insertService()

	def set3DMode(self, value):
		playingref = self.session.nav.getCurrentlyPlayingServiceReference()
		if config.plugins.OSD3DSetup.mode.value == "auto" and (playingref and playingref == self.csel.getCurrentSelection()):
			from Plugins.SystemPlugins.OSD3DSetup.plugin import applySettings
			applySettings(value and "sidebyside" or config.plugins.OSD3DSetup.mode.value)

	def addDedicated3DFlag(self):
		eDVBDB.getInstance().addFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_IS_DEDICATED_3D)
		eDVBDB.getInstance().reloadBouquets()
		self.set3DMode(True)
		self.close()

	def removeDedicated3DFlag(self):
		eDVBDB.getInstance().removeFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_IS_DEDICATED_3D)
		eDVBDB.getInstance().reloadBouquets()
		self.set3DMode(False)
		self.close()

	def toggleVBI(self):
		Screens.InfoBar.InfoBar.instance.ToggleHideVBI(self.csel.getCurrentSelection())
		Screens.InfoBar.InfoBar.instance.showHideVBI()
		self.close()

	def toggleBouquet(self):
		Screens.InfoBar.InfoBar.instance.ToggleBouquet(self.csel.getCurrentSelection().toString().split('"')[1])
		self.close()

	def toggleStreamrelay(self):
		Screens.InfoBar.InfoBar.instance.ToggleStreamrelay(self.csel.getCurrentSelection())
		self.close()

	def addCenterDVBSubsFlag(self):
		eDVBDB.getInstance().addFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_CENTER_DVB_SUBS)
		eDVBDB.getInstance().reloadBouquets()
		config.subtitles.dvb_subtitles_centered.value = True
		self.close()

	def removeCenterDVBSubsFlag(self):
		eDVBDB.getInstance().removeFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_CENTER_DVB_SUBS)
		eDVBDB.getInstance().reloadBouquets()
		config.subtitles.dvb_subtitles_centered.value = False
		self.close()

	def isProtected(self):
		return self.csel.protectContextMenu and config.ParentalControl.setuppinactive.value and config.ParentalControl.config_sections.context_menus.value

	def protectResult(self, answer):
		if answer:
			self.csel.protectContextMenu = False
		elif answer is not None:
			self.session.openWithCallback(self.close, MessageBox, _("The PIN code you entered is wrong."), MessageBox.TYPE_ERROR)
		else:
			self.close()

	def addNoAITranslationFlag(self):
		eDVBDB.getInstance().addFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_NO_AI_TRANSLATION)
		eDVBDB.getInstance().reloadBouquets()
		self.close()

	def removeNoAITranslationFlag(self):
		eDVBDB.getInstance().removeFlag(eServiceReference(self.csel.getCurrentSelection().toString()), FLAG_NO_AI_TRANSLATION)
		eDVBDB.getInstance().reloadBouquets()
		self.close()

	def addServiceToBouquetOrAlternative(self):
		if self.addFunction:
			self.addFunction()
		else:
			return 0

	def getCurrentSelectionName(self):
		cur = self.csel.getCurrentSelection()
		if cur and cur.valid():
			name = eServiceCenter.getInstance().info(cur) and hasattr(eServiceCenter.getInstance().info(cur), "getName") and eServiceCenter.getInstance().info(cur).getName(cur) or ServiceReference(cur).getServiceName() or ""
			name = name.replace('\xc2\x86', '').replace('\xc2\x87', '')
			return name
		return ""

	def insertService(self):
		self.session.openWithCallback(self.insertServiceCallback, InsertService)

	def insertServiceCallback(self, answer=None):
		if answer:
			self.csel.insertService(answer)
			self.close()

	def removeEntry(self):
		if self.removeFunction and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid():
			if self.csel.confirmRemove:
				list = [(_("yes"), True), (_("no"), False), (_("yes") + " " + _("and never ask in this session again"), "never")]
				self.session.openWithCallback(self.removeFunction, MessageBox, f"{_('Are you sure to remove this entry?')}\n{self.getCurrentSelectionName()}", list=list)
			else:
				self.removeFunction(True)
		else:
			return 0

	def removeCurrentService(self, answer):
		if answer:
			if answer == "never":
				self.csel.confirmRemove = False
			self.csel.removeCurrentService()
			self.close()

	def removeSatelliteService(self, answer):
		if answer:
			if answer == "never":
				self.csel.confirmRemove = False
			self.csel.removeSatelliteService()
			self.close()

	def removeBouquet(self, answer):
		if answer:
			if answer == "never":
				self.csel.confirmRemove = False
			if self.csel.movemode:
				self.csel.toggleMoveMode()
			self.csel.removeBouquet()
			eDVBDB.getInstance().reloadBouquets()
			self.close()

	def purgeDeletedBouquets(self):
		self.session.openWithCallback(self.purgeDeletedBouquetsCallback, MessageBox, _("Are you sure to purge all deleted user bouquets?"))

	def purgeDeletedBouquetsCallback(self, answer):
		if answer:
			for file in os.listdir("/etc/enigma2/"):
				if file.startswith("userbouquet") and file.endswith(".del"):
					file = "/etc/enigma2/" + file
					print(f"[ChannelSelection] Permanently remove file '{file}'.")
					os.remove(file)
			self.close()

	def restoreDeletedBouquets(self):
		for file in os.listdir("/etc/enigma2/"):
			if file.startswith("userbouquet") and file.endswith(".del"):
				file = "/etc/enigma2/" + file
				print(f"[ChannelSelection] Restore file '{file[:-4]}'.")
				os.rename(file, file[:-4])
		eDVBDBInstance = eDVBDB.getInstance()
		eDVBDBInstance.setLoadUnlinkedUserbouquets(1)
		eDVBDBInstance.reloadBouquets()
		eDVBDBInstance.setLoadUnlinkedUserbouquets(int(config.misc.load_unlinked_userbouquets.value))
		refreshServiceList()
		self.csel.showFavourites()
		self.close()

	def playMain(self):
		ref = self.csel.getCurrentSelection()
		if ref and ref.valid() and self.PiPAvailable and self.csel.dopipzap:
			self.csel.zap()
			self.csel.startServiceRef = None
			self.csel.startRoot = None
			self.csel.correctChannelNumber()
			self.close(True)
		else:
			return 0

	def okbuttonClick(self):
		self["menu"].getCurrent()[0][1]()

	def openSetup(self):
		self.session.openWithCallback(self.cancelClick, ChannelSelectionSetup)

	def cancelClick(self, dummy=False):
		self.close(False)

	def reloadServicesBouquets(self):
		eDVBDB.getInstance().reloadServicelist()
		eDVBDB.getInstance().reloadBouquets()
		self.session.openWithCallback(self.close, MessageBox, _("The services/bouquets list is reloaded!"), MessageBox.TYPE_INFO, timeout=5)

	def showServiceInformations(self):
		current = self.csel.getCurrentSelection()
		if current.flags & eServiceReference.isGroup:
			playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if playingref and playingref == current:
				current = self.session.nav.getCurrentlyPlayingServiceReference()
			else:
				current = eServiceReference(GetWithAlternative(current.toString()))
		self.session.openWithCallback(self.close, ServiceInfo, current)

	def showSubservices(self):
		self.csel.enterSubservices(self.csel.getCurrentSelection(), self.subservices)
		self.close()

	def setStartupService(self):
		self.session.openWithCallback(self.setStartupServiceCallback, MessageBox, _("Set startup service"), list=[(_("Only on startup"), "startup"), (_("Also on standby"), "standby")])

	def setStartupServiceCallback(self, answer):
		if answer:
			config.servicelist.startupservice.value = self.csel.getCurrentSelection().toString()
			path = ';'.join([i.toString() for i in self.csel.servicePath])
			config.servicelist.startuproot.value = path
			config.servicelist.startupmode.value = config.servicelist.lastmode.value
			config.servicelist.startupservice_onstandby.value = answer == "standby"
			config.servicelist.save()
			configfile.save()
			self.close()

	def unsetStartupService(self):
		config.servicelist.startupservice.value = ''
		config.servicelist.startupservice_onstandby.value = False
		config.servicelist.save()
		configfile.save()
		self.close()

	def showBouquetInputBox(self):
		self.session.openWithCallback(self.bouquetInputCallback, VirtualKeyBoard, title=_("Please enter a name for the new bouquet"), text="", maxSize=False, visible_width=56, type=Input.TEXT)

	def bouquetInputCallback(self, bouquet):
		if bouquet is not None:
			self.csel.addBouquet(bouquet, None)
		self.close()

	def addParentalProtection(self, service):
		self.parentalControl.protectService(service.toCompareString())
		if config.ParentalControl.hideBlacklist.value and not self.parentalControl.sessionPinCached:
			self.csel.servicelist.resetRoot()
		self.close()

	def removeParentalProtection(self, service):
		self.session.openWithCallback(boundFunction(self.pinEntered, service.toCompareString()), PinInput, pinList=[config.ParentalControl.servicepin[0].value], triesEntry=config.ParentalControl.retries.servicepin, title=_("Enter the service PIN"), windowTitle=_("Enter PIN code"))

	def pinEntered(self, service, answer):
		if answer:
			self.parentalControl.unProtectService(service)
			if config.ParentalControl.hideBlacklist.value and not self.parentalControl.sessionPinCached:
				self.csel.servicelist.resetRoot()
			self.close()
		elif answer is not None:
			self.session.openWithCallback(self.close, MessageBox, _("The PIN code you entered is wrong."), MessageBox.TYPE_ERROR)
		else:
			self.close()

	def unhideParentalServices(self):
		if self.csel.protectContextMenu:
			self.session.openWithCallback(self.unhideParentalServicesCallback, PinInput, pinList=[config.ParentalControl.servicepin[0].value], triesEntry=config.ParentalControl.retries.servicepin, title=_("Enter the service PIN"), windowTitle=_("Enter PIN code"))
		else:
			self.unhideParentalServicesCallback(True)

	def unhideParentalServicesCallback(self, answer):
		if answer:
			service = self.csel.servicelist.getCurrent()
			self.parentalControl.setSessionPinCached()
			self.parentalControl.hideBlacklist()
			self.csel.servicelist.resetRoot()
			self.csel.servicelist.setCurrent(service)
			self.close()
		elif answer is not None:
			self.session.openWithCallback(self.close, MessageBox, _("The PIN code you entered is wrong."), MessageBox.TYPE_ERROR)
		else:
			self.close()

	def showServiceInPiP(self, root=None, ref=None):
		newservice = ref or self.csel.getCurrentSelection()
		currentBouquet = root or self.csel.getRoot()
		if ref and root or (self.PiPAvailable and not self.csel.dopipzap and newservice and newservice.valid() and Components.ParentalControl.parentalControl.isServicePlayable(newservice, boundFunction(self.showServiceInPiP, root=currentBouquet), self.session)):
			if hasattr(self.session, 'pipshown') and self.session.pipshown and hasattr(self.session, 'pip'):
				del self.session.pip
			self.session.pip = self.session.instantiateDialog(PictureInPicture)
			self.session.pip.show()
			if self.session.pip.playService(newservice):
				self.session.pipshown = True
				self.session.pip.servicePath = self.csel.getCurrentServicePath()
				self.session.pip.servicePath[1] = currentBouquet
				self.close(True)
			else:
				self.session.pipshown = False
				del self.session.pip
				self.session.openWithCallback(self.close, MessageBox, _("Could not open Picture in Picture"), MessageBox.TYPE_ERROR)
		else:
			return 0

	def addServiceToBouquetSelected(self):
		bouquets = self.csel.getBouquetList()
		if bouquets is None:
			cnt = 0
		else:
			cnt = len(bouquets)
		if cnt > 1: # show bouquet list
			self.bsel = self.session.openWithCallback(self.bouquetSelClosed, BouquetSelector, bouquets, self.addCurrentServiceToBouquet)
		elif cnt == 1: # add to only one existing bouquet
			self.addCurrentServiceToBouquet(bouquets[0][1], closeBouquetSelection=False)

	def bouquetSelClosed(self, recursive):
		self.bsel = None
		if recursive:
			self.close(False)

	def removeSatelliteServices(self):
		self.csel.removeSatelliteServices()
		self.close()

	def copyCurrentToBouquetList(self):
		self.csel.copyCurrentToBouquetList()
		self.close()

	def copyCurrentToStreamRelay(self):
		self.csel.copyCurrentToStreamRelay()
		self.close()

	def showMarkerInputBox(self):
		self.session.openWithCallback(self.markerInputCallback, VirtualKeyBoard, title=_("Please enter a name for the new marker"), text="markername", maxSize=False, visible_width=56, type=Input.TEXT)

	def markerInputCallback(self, marker):
		if marker is not None:
			self.csel.addMarker(marker)
		self.close()

	def addCurrentServiceToBouquet(self, dest, closeBouquetSelection=True):
		self.csel.addServiceToBouquet(dest)
		if self.bsel is not None:
			self.bsel.close(True)
		else:
			self.close(closeBouquetSelection) # close bouquet selection

	def renameEntry(self):
		if self.inBouquet and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid() and not self.csel.entry_marked:
			self.csel.renameEntry()
			self.close()
		else:
			return 0

	def toggleMoveMode(self):
		if self.inBouquet and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid():
			self.csel.toggleMoveMode()
			self.close()
		else:
			return 0

	def toggleMoveModeSelect(self):
		if self.inBouquet and self.csel.servicelist.getCurrent() and self.csel.servicelist.getCurrent().valid():
			self.csel.toggleMoveMode(True)
			self.close()
		else:
			return 0

	def bouquetMarkStart(self):
		self.csel.startMarkedEdit(EDIT_BOUQUET)
		self.close()

	def bouquetMarkEnd(self):
		self.csel.endMarkedEdit(abort=False)
		self.close()

	def bouquetMarkAbort(self):
		self.csel.endMarkedEdit(abort=True)
		self.close()

	def removeNewFoundFlag(self):
		eDVBDB.getInstance().removeFlag(self.csel.getCurrentSelection(), FLAG_SERVICE_NEW_FOUND)
		self.close()

	def removeAllNewFoundFlags(self):
		curpath = self.csel.getCurrentSelection().getPath()
		idx = curpath.find("satellitePosition == ")
		if idx != -1:
			tmp = curpath[idx + 21:]
			idx = tmp.find(')')
			if idx != -1:
				satpos = int(tmp[:idx])
				eDVBDB.getInstance().removeFlags(FLAG_SERVICE_NEW_FOUND, -1, -1, -1, satpos)
		self.close()

	def editAlternativeServices(self):
		self.csel.startMarkedEdit(EDIT_ALTERNATIVES)
		self.close()

	def showAlternativeServices(self):
		self.csel["Service"].editmode = True
		self.csel.enterPath(self.csel.getCurrentSelection())
		self.close()

	def removeAlternativeServices(self):
		self.csel.removeAlternativeServices()
		self.close()

	def addAlternativeServices(self):
		self.csel.addAlternativeServices()
		self.csel.startMarkedEdit(EDIT_ALTERNATIVES)
		self.close()

	def findCurrentlyPlayed(self):
		sel = self.csel.getCurrentSelection()
		if sel and sel.valid() and not self.csel.entry_marked:
			currentPlayingService = (hasattr(self.csel, "dopipzap") and self.csel.dopipzap) and self.session.pip.getCurrentService() or self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if currentPlayingService:
				self.csel.servicelist.setCurrent(currentPlayingService, adjust=False)
				if self.csel.getCurrentSelection() != currentPlayingService:
					self.csel.setCurrentSelection(sel)
				self.close()
		else:
			return 0

	def runPlugin(self, plugin):
		plugin(session=self.session, service=self.csel.getCurrentSelection())
		self.close()


class SelectionEventInfo:
	def __init__(self):
		self["Service"] = self["ServiceEvent"] = ServiceEvent()
		self["Event"] = Event()
		self.servicelist.connectSelChanged(self.__selectionChanged)
		self.timer = eTimer()
		self.timer.callback.append(self.updateEventInfo)
		self.onShown.append(self.__selectionChanged)
		self.onHide.append(self.__stopTimer)
		self.currentBouquetPath = ""
		self.newBouquet = ""

	def __stopTimer(self):
		self.timer.stop()

	def __selectionChanged(self):
		self.timer.stop()
		if self.execing:
			self.update_root = False
			self.timer.start(100, True)

	def updateBouquetPath(self, newBouquetPath):
		if self.currentBouquetPath != newBouquetPath:
			self.currentBouquetPath = newBouquetPath
			if "FROM BOUQUET" in self.currentBouquetPath:
				currentBouquet = [x for x in self.currentBouquetPath.split(";") if x]
				currentBouquet = currentBouquet[-1] if currentBouquet else ""
				serviceHandler = eServiceCenter.getInstance()
				bouquet = eServiceReference(currentBouquet)
				info = serviceHandler.info(bouquet)
				name = info and info.getName(bouquet) or ""
			elif "FROM PROVIDERS" in self.currentBouquetPath:
				name = _("Provider")
			elif "FROM SATELLITES" in self.currentBouquetPath:
				name = _("Satellites")
			elif ") ORDER BY name" in self.currentBouquetPath:
				name = _("All Services")
			else:
				name = "N/A"
			if self.newBouquet != name:
				self.newBouquet = name
				self.session.nav.currentBouquetName = name

	def updateEventInfo(self):
		cur = self.getCurrentSelection()
		service = self["Service"]
		try:
			service.newService(cur)
			self["Event"].newEvent(service.event)
			if self.newBouquet:
				service.newBouquetName(self.newBouquet)
				self.newBouquet = ""
			if cur and service.event:
				if self.update_root and self.shown and self.getMutableList():
					root = self.getRoot()
					if root and hasattr(self, "editMode") and not self.editMode:
						self.clearPath()
						if self.bouquet_root:
							self.enterPath(self.bouquet_root)
						self.enterPath(root)
						self.setCurrentSelection(cur)
						self.update_root = False
				if not self.update_root:
					now = int(time())
					end_time = service.event.getBeginTime() + service.event.getDuration()
					if end_time > now:
						self.update_root = True
						self.timer.start((end_time - now) * 1000, True)
		except:
			pass


class ChannelSelectionEPG(InfoBarHotkey):
	def __init__(self):
		self.hotkeys = [("Info (EPG)", "info", "Infobar/openEventView"),
			("Info (EPG)" + " " + _("long"), "info_long", "Infobar/showEventInfoPlugins"),
			("EPG/Guide", "epg", "Plugins/Extensions/GraphMultiEPG/1"),
			("EPG/Guide" + " " + _("long"), "epg_long", "Infobar/showEventInfoPlugins")]
		self["ChannelSelectEPGActions"] = hotkeyActionMap(["ChannelSelectEPGActions"], dict((x[1], self.hotkeyGlobal) for x in self.hotkeys))
		self.eventViewEPG = self.start_bouquet = self.epg_bouquet = None
		self.currentSavedPath = []

	def getKeyFunctions(self, key):
		selection = eval("config.misc.hotkey." + key + ".value.split(',')")
		selected = []
		for x in selection:
			function = list(function for function in hotkey.functions if function[1] == x and function[2] == "EPG")
			if function:
				selected.append(function[0])
		return selected

	def runPlugin(self, plugin):
		Screens.InfoBar.InfoBar.instance.runPlugin(plugin)

	def getEPGPluginList(self, getAll=False):
		pluginlist = [(p.name, boundFunction(self.runPlugin, p), p.description or p.name) for p in plugins.getPlugins(where=PluginDescriptor.WHERE_EVENTINFO)
				if 'selectedevent' not in p.fnc.__code__.co_varnames] or []
		from Components.ServiceEventTracker import InfoBarCount
		if getAll or InfoBarCount == 1:
			pluginlist.append((_("Show EPG for current channel..."), self.openSingleServiceEPG, _("Display EPG list for current channel")))
		pluginlist.append((_("Multi EPG"), self.openMultiServiceEPG, _("Display EPG as MultiEPG")))
		pluginlist.append((_("Current event EPG"), self.openEventView, _("Display EPG info for current event")))
		return pluginlist

	def showEventInfoPlugins(self):
		pluginlist = self.getEPGPluginList()
		if pluginlist:
			self.session.openWithCallback(self.EventInfoPluginChosen, ChoiceBox, title=_("Please choose an extension..."), list=pluginlist, skin_name="EPGExtensionsList")
		else:
			self.openSingleServiceEPG()

	def EventInfoPluginChosen(self, answer):
		if answer is not None:
			answer[1]()

	def openEventView(self):
		epglist = []
		self.epglist = epglist
		ref = self.getCurrentSelection()
		epg = eEPGCache.getInstance()
		now_event = epg.lookupEventTime(ref, -1, 0)
		if now_event:
			epglist.append(now_event)
			next_event = epg.lookupEventTime(ref, -1, 1)
			if next_event:
				epglist.append(next_event)
		if epglist:
			self.eventViewEPG = self.session.openWithCallback(self.eventViewEPGClosed, EventViewEPGSelect, epglist[0], ServiceReference(ref), self.eventViewEPGCallback, self.openSingleServiceEPG, self.openMultiServiceEPG, self.openSimilarList)

	def eventViewEPGCallback(self, setEvent, setService, val):
		epglist = self.epglist
		if len(epglist) > 1:
			tmp = epglist[0]
			epglist[0] = epglist[1]
			epglist[1] = tmp
			setEvent(epglist[0])

	def eventViewEPGClosed(self, ret=False):
		self.eventViewEPG = None
		if ret:
			self.close()

	def openMultiServiceEPG(self):
		ref = self.getCurrentSelection()
		if ref:
			self.start_bouquet = self.epg_bouquet = self.servicelist.getRoot()
			self.savedService = ref
			self.currentSavedPath = self.servicePath[:]
			services = self.getServicesList(self.servicelist.getRoot())
			self.session.openWithCallback(self.SingleMultiEPGClosed, EPGSelection, services, self.zapToService, None, bouquetChangeCB=self.changeBouquetForMultiEPG)

	def openSingleServiceEPG(self):
		ref = self.getCurrentSelection()
		if ref:
			self.start_bouquet = self.epg_bouquet = self.servicelist.getRoot()
			self.savedService = ref
			self.currentSavedPath = self.servicePath[:]
			self.session.openWithCallback(self.SingleMultiEPGClosed, EPGSelection, ref, self.zapToService, serviceChangeCB=self.changeServiceCB, bouquetChangeCB=self.changeBouquetForSingleEPG)

	def openSimilarList(self, eventid, refstr):
		self.session.open(EPGSelection, refstr, None, eventid)

	def getServicesList(self, root):
		services = []
		servicelist = root and eServiceCenter.getInstance().list(root)
		if not servicelist is None:
			while True:
				service = servicelist.getNext()
				if not service.valid():
					break
				if service.flags & (eServiceReference.isDirectory | eServiceReference.isMarker):
					continue
				services.append(ServiceReference(service))
		return services

	def SingleMultiEPGClosed(self, ret=False):
		if ret:
			service = self.getCurrentSelection()
			if self.eventViewEPG:
				self.eventViewEPG.close(service)
			elif service is not None:
				self.close()
		else:
			if self.start_bouquet != self.epg_bouquet and len(self.currentSavedPath) > 0:
				self.clearPath()
				self.enterPath(self.bouquet_root)
				self.epg_bouquet = self.start_bouquet
				self.enterPath(self.epg_bouquet)
			self.setCurrentSelection(self.savedService)

	def changeBouquetForSingleEPG(self, direction, epg):
		if config.usage.multibouquet.value:
			inBouquet = self.getMutableList() is not None
			if inBouquet and len(self.servicePath) > 1:
				self.pathUp()
				if direction < 0:
					self.moveUp()
				else:
					self.moveDown()
				cur = self.getCurrentSelection()
				self.enterPath(cur)
				self.epg_bouquet = self.servicelist.getRoot()
				epg.setService(ServiceReference(self.getCurrentSelection()))

	def changeBouquetForMultiEPG(self, direction, epg):
		if config.usage.multibouquet.value:
			inBouquet = self.getMutableList() is not None
			if inBouquet and len(self.servicePath) > 1:
				self.pathUp()
				if direction < 0:
					self.moveUp()
				else:
					self.moveDown()
				cur = self.getCurrentSelection()
				self.enterPath(cur)
				self.epg_bouquet = self.servicelist.getRoot()
				services = self.getServicesList(self.epg_bouquet)
				epg.setServices(services)

	def changeServiceCB(self, direction, epg):
		beg = self.getCurrentSelection()
		while True:
			if direction > 0:
				self.moveDown()
			else:
				self.moveUp()
			cur = self.getCurrentSelection()
			if cur == beg or not (cur.flags & eServiceReference.isMarker):
				break
		epg.setService(ServiceReference(self.getCurrentSelection()))

	def zapToService(self, service, preview=False, zapback=False):
		if self.startServiceRef is None:
			self.startServiceRef = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if service is not None:
			if self.servicelist.getRoot() != self.epg_bouquet:
				self.servicelist.clearPath()
				if self.servicelist.bouquet_root != self.epg_bouquet:
					self.servicelist.enterPath(self.servicelist.bouquet_root)
				self.servicelist.enterPath(self.epg_bouquet)
			self.servicelist.setCurrent(service)
		if not zapback or preview:
			self.zap(enable_pipzap=True)
		if (self.dopipzap or zapback) and not preview:
			self.zapBack()
		if not preview:
			self.startServiceRef = None
			self.startRoot = None
			self.revertMode = None


class ChannelSelectionEdit:
	def __init__(self):
		self.entry_marked = False
		self.bouquet_mark_edit = OFF
		self.mutableList = None
		self.__marked = []
		self.saved_title = None
		self.saved_root = None
		self.current_ref = None
		self.editMode = False
		self.confirmRemove = True

		class ChannelSelectionEditActionMap(ActionMap):
			def __init__(self, csel, contexts=[], actions={}, prio=0):
				ActionMap.__init__(self, contexts, actions, prio)
				self.csel = csel

			def action(self, contexts, action):
				if action == "cancel":
					self.csel.handleEditCancel()
					return 0 # fall-trough
				elif action == "ok":
					return 0 # fall-trough
				else:
					return ActionMap.action(self, contexts, action)

		self["ChannelSelectEditActions"] = ChannelSelectionEditActionMap(self, ["ChannelSelectEditActions", "OkCancelActions"],
			{
				"contextMenu": self.doContext,
			})

	def getMutableList(self, root=eServiceReference()):
		if not self.mutableList is None:
			return self.mutableList
		serviceHandler = eServiceCenter.getInstance()
		if not root.valid():
			root = self.getRoot()
		list = root and serviceHandler.list(root)
		if list is not None:
			return list.startEdit()
		return None

	def renameEntry(self):
		self.editMode = True
		cur = self.getCurrentSelection()
		if cur and cur.valid():
			name = eServiceCenter.getInstance().info(cur) and hasattr(eServiceCenter.getInstance().info(cur), "getName") and eServiceCenter.getInstance().info(cur).getName(cur) or ServiceReference(cur).getServiceName() or ""
			name = name.replace('\xc2\x86', '').replace('\xc2\x87', '')
			if name:
				self.session.openWithCallback(self.renameEntryCallback, VirtualKeyBoard, title=_("Please enter new name:"), text=name)
		else:
			return 0

	def renameEntryCallback(self, name):
		if name:
			mutableList = self.getMutableList()
			if mutableList:
				current = self.servicelist.getCurrent()
				current.setName(name)
				index = self.servicelist.getCurrentIndex()
				mutableList.removeService(current, False)
				mutableList.addService(current)
				mutableList.moveService(current, index)
				mutableList.flushChanges()
				self.servicelist.addService(current, True)
				self.servicelist.removeCurrent()
				if not self.servicelist.atEnd():
					self.servicelist.moveUp()

	def insertService(self, serviceref):
		current = self.servicelist.getCurrent()
		mutableList = self.getMutableList()
		if mutableList:
			if not mutableList.addService(serviceref, current):
				mutableList.flushChanges()
				self.servicelist.addService(serviceref, True)
				self.servicelist.resetRoot()

	def addMarker(self, name):
		current = self.servicelist.getCurrent()
		mutableList = self.getMutableList()
		cnt = 0
		while mutableList:
			ref = eServiceReference(eServiceReference.idDVB, eServiceReference.isMarker, cnt)
			ref.setName(name)
			if current and current.valid():
				if not mutableList.addService(ref, current):
					self.servicelist.addService(ref, True)
					mutableList.flushChanges()
					break
			elif not mutableList.addService(ref):
				self.servicelist.addService(ref, True)
				mutableList.flushChanges()
				break
			cnt += 1

	def addAlternativeServices(self):
		cur_service = ServiceReference(self.getCurrentSelection())
		end = self.atEnd()
		root = self.getRoot()
		cur_root = root and ServiceReference(root)
		mutableBouquet = cur_root.list().startEdit()
		if mutableBouquet:
			name = cur_service.getServiceName()
			flags = eServiceReference.isGroup | eServiceReference.canDescent | eServiceReference.mustDescent
			if self.mode == MODE_TV:
				ref = eServiceReference(eServiceReference.idDVB, flags, eServiceReferenceDVB.dTv)
				ref.setPath('FROM BOUQUET "alternatives.%s.tv" ORDER BY bouquet' % self.buildBouquetID(name))
			else:
				ref = eServiceReference(eServiceReference.idDVB, flags, eServiceReferenceDVB.dRadio)
				ref.setPath('FROM BOUQUET "alternatives.%s.radio" ORDER BY bouquet' % self.buildBouquetID(name))
			new_ref = ServiceReference(ref)
			if not mutableBouquet.addService(new_ref.ref, cur_service.ref):
				mutableBouquet.removeService(cur_service.ref)
				mutableBouquet.flushChanges()
				eDVBDB.getInstance().reloadBouquets()
				mutableAlternatives = new_ref.list().startEdit()
				if mutableAlternatives:
					mutableAlternatives.setListName(name)
					if mutableAlternatives.addService(cur_service.ref):
						print(f"[ChannelSelection] Add '{cur_service.ref.toString()}' to new alternatives failed!")
					mutableAlternatives.flushChanges()
					self.servicelist.addService(new_ref.ref, True)
					self.servicelist.removeCurrent()
					if not end:
						self.servicelist.moveUp()
					if cur_service.ref.toString() == self.lastservice.value:
						self.saveChannel(new_ref.ref)
					if self.startServiceRef and cur_service.ref == self.startServiceRef:
						self.startServiceRef = new_ref.ref
				else:
					print("get mutable list for new created alternatives failed")
			else:
				print(f"[ChannelSelection] Add '{str}' to '{cur_root.getServiceName()}' failed!")
		else:
			print("bouquetlist is not editable")

	def addBouquet(self, bName, services):
		serviceHandler = eServiceCenter.getInstance()
		mutableBouquetList = serviceHandler.list(self.bouquet_root).startEdit()
		if mutableBouquetList:			
			if self.mode == MODE_TV:
				bName = f"{bName} {_('(TV)')}"
				new_bouquet_ref = eServiceReference(service_types_tv_ref)
				new_bouquet_ref.setPath("FROM BOUQUET \"userbouquet.%s.tv\" ORDER BY bouquet" % self.buildBouquetID(bName))
			else:
				bName = f"{bName} {_('(Radio)')}"
				new_bouquet_ref = eServiceReference(service_types_radio_ref)
				new_bouquet_ref.setPath("FROM BOUQUET \"userbouquet.%s.radio\" ORDER BY bouquet" % self.buildBouquetID(bName))
			if not mutableBouquetList.addService(new_bouquet_ref):
				mutableBouquetList.flushChanges()
				eDVBDB.getInstance().reloadBouquets()
				mutableBouquet = serviceHandler.list(new_bouquet_ref).startEdit()
				if mutableBouquet:
					mutableBouquet.setListName(bName)
					if services is not None:
						for service in services:
							if mutableBouquet.addService(service):
								print(f"[ChannelSelection] Add '{service.toString()}' to new bouquet failed!")
					mutableBouquet.flushChanges()
				else:
					print("get mutable list for new created bouquet failed")
				# do some voodoo to check if current_root is equal to bouquet_root
				cur_root = self.getRoot()
				str1 = cur_root and cur_root.getPath()
				pos1 = str1.find("FROM BOUQUET") if str1 else -1
				pos2 = self.bouquet_root.getPath().find("FROM BOUQUET")
				if pos1 != -1 and pos2 != -1 and str1[pos1:] == self.bouquet_rootstr[pos2:]:
					self.servicelist.addService(new_bouquet_ref)
					self.servicelist.resetRoot()
			else:
				print(f"[ChannelSelection] Add '{new_bouquet_ref.toString()}' to bouquets failed!")
		else:
			print("[ChannelSelection] The bouquet list is not editable.")

	def copyCurrentToBouquetList(self):
		provider = ServiceReference(self.getCurrentSelection())
		providerName = provider.getServiceName()
		serviceHandler = eServiceCenter.getInstance()
		services = serviceHandler.list(provider.ref)
		self.addBouquet(providerName, services and services.getContent('R', True))

	def copyCurrentToStreamRelay(self):
		provider = ServiceReference(self.getCurrentSelection())
		serviceHandler = eServiceCenter.getInstance()
		services = serviceHandler.list(provider.ref)
		Screens.InfoBar.InfoBar.instance.ToggleStreamrelay(services and services.getContent("R", True))

	def removeAlternativeServices(self):
		cur_service = ServiceReference(self.getCurrentSelection())
		end = self.atEnd()
		root = self.getRoot()
		cur_root = root and ServiceReference(root)
		list = cur_service.list()
		first_in_alternative = list and list.getNext()
		if first_in_alternative:
			edit_root = cur_root and cur_root.list().startEdit()
			if edit_root:
				if not edit_root.addService(first_in_alternative, cur_service.ref):
					self.servicelist.addService(first_in_alternative, True)
					if cur_service.ref.toString() == self.lastservice.value:
						self.saveChannel(first_in_alternative)
					if self.startServiceRef and cur_service.ref == self.startServiceRef:
						self.startServiceRef = first_in_alternative
				else:
					print("couldn't add first alternative service to current root")
			else:
				print("couldn't edit current root!!")
		else:
			print("remove empty alternative list !!")
		self.removeBouquet()
		if not end:
			self.servicelist.moveUp()

	def removeBouquet(self):
		refstr = self.getCurrentSelection().toString()
		print(f"[ChannelSelection] removeBouquet {refstr}")
		pos = refstr.find('FROM BOUQUET "')
		filename = None
		self.removeCurrentService(bouquet=True)

	def removeSatelliteService(self):
		current = self.getCurrentSelection()
		eDVBDB.getInstance().removeService(current)
		refreshServiceList()
		if not self.atEnd():
			self.servicelist.moveUp()

	def removeSatelliteServices(self):
		current = self.getCurrentSelection()
		unsigned_orbpos = current.getUnsignedData(4) >> 16
		if unsigned_orbpos == 0xFFFF:
			messageText = _("Are you sure to remove all cable services?")
		elif unsigned_orbpos == 0xEEEE:
			messageText = _("Are you sure to remove all terrestrial services?")
		else:
			if unsigned_orbpos > 1800:
				orbpos = _("%.1f° W") % ((3600 - unsigned_orbpos) / 10.0)
			else:
				orbpos = _("%.1f° E") % (unsigned_orbpos / 10.0)
			# TRANSLATORS: The user is asked to delete all satellite services from a specific orbital position after a configuration change
			messageText = _("Are you sure to remove all %s services?") % orbpos
		self.session.openWithCallback(self.removeSatelliteServicesCallback, MessageBox, messageText)

	def removeSatelliteServicesCallback(self, answer):
		if answer:
			currentIndex = self.servicelist.getCurrentIndex()
			current = self.getCurrentSelection()
			unsigned_orbpos = current.getUnsignedData(4) >> 16
			if unsigned_orbpos == 0xFFFF:
				eDVBDB.getInstance().removeServices(int("0xFFFF0000", 16) - 0x100000000)
			elif unsigned_orbpos == 0xEEEE:
				eDVBDB.getInstance().removeServices(int("0xEEEE0000", 16) - 0x100000000)
			else:
				curpath = current.getPath()
				idx = curpath.find("satellitePosition == ")
				if idx != -1:
					tmp = curpath[idx + 21:]
					idx = tmp.find(')')
					if idx != -1:
						satpos = int(tmp[:idx])
						eDVBDB.getInstance().removeServices(-1, -1, -1, satpos)
			refreshServiceList()
			if hasattr(self, 'showSatellites'):
				self.showSatellites()
				self.servicelist.moveToIndex(currentIndex)
				if currentIndex != self.servicelist.getCurrentIndex():
					self.servicelist.instance.moveSelection(self.servicelist.instance.moveEnd)

#  multiple marked entry stuff ( edit mode, later multiepg selection )
	def startMarkedEdit(self, type):
		self.savedPath = self.servicePath[:]
		if type == EDIT_ALTERNATIVES:
			self.current_ref = self.getCurrentSelection()
			self.enterPath(self.current_ref)
		self.mutableList = self.getMutableList()
		# add all services from the current list to internal marked set in listboxservicecontent
		self.clearMarks() # this clears the internal marked set in the listboxservicecontent
		if type == EDIT_ALTERNATIVES:
			self.bouquet_mark_edit = EDIT_ALTERNATIVES
			self.functiontitle = ' ' + _("[alternative edit]")
		else:
			self.bouquet_mark_edit = EDIT_BOUQUET
			if config.usage.multibouquet.value:
				self.functiontitle = ' ' + _("[bouquet edit]")
			else:
				self.functiontitle = ' ' + _("[favourite edit]")
		self.compileTitle()
		self.__marked = self.servicelist.getRootServices()
		for x in self.__marked:
			self.servicelist.addMarked(eServiceReference(x))
		self["Service"].editmode = True

	def endMarkedEdit(self, abort):
		if not abort and self.mutableList is not None:
			new_marked = set(self.servicelist.getMarked())
			old_marked = set(self.__marked)
			removed = old_marked - new_marked
			added = new_marked - old_marked
			changed = False
			for x in removed:
				changed = True
				self.mutableList.removeService(eServiceReference(x))
			for x in added:
				changed = True
				self.mutableList.addService(eServiceReference(x))
			if changed:
				if self.bouquet_mark_edit == EDIT_ALTERNATIVES and not new_marked and self.__marked:
					self.mutableList.addService(eServiceReference(self.__marked[0]))
				self.mutableList.flushChanges()
		self.__marked = []
		self.clearMarks()
		self.bouquet_mark_edit = OFF
		self.mutableList = None
		self.functiontitle = ""
		self.compileTitle()
		# self.servicePath is just a reference to servicePathTv or Radio...
		# so we never ever do use the asignment operator in self.servicePath
		del self.servicePath[:] # remove all elements
		self.servicePath += self.savedPath # add saved elements
		del self.savedPath
		self.setRoot(self.servicePath[-1])
		if self.current_ref:
			self.setCurrentSelection(self.current_ref)
			self.current_ref = None

	def clearMarks(self):
		self.servicelist.clearMarks()

	def doMark(self):
		ref = self.servicelist.getCurrent()
		if self.servicelist.isMarked(ref):
			self.servicelist.removeMarked(ref)
		else:
			self.servicelist.addMarked(ref)

	def buildBouquetID(self, str):
		tmp = str.lower()
		name = ""
		for c in tmp:
			if ("a" <= c <= "z") or ("0" <= c <= "9"):
				name += c
			else:
				name += "_"
		return name

	def removeCurrentEntry(self, bouquet=False):
		if self.confirmRemove:
			list = [(_("yes"), True), (_("no"), False), (_("yes") + " " + _("and never ask in this session again"), "never")]
			self.session.openWithCallback(boundFunction(self.removeCurrentEntryCallback, bouquet), MessageBox, _("Are you sure to remove this entry?"), list=list)
		else:
			self.removeCurrentEntryCallback(bouquet, True)

	def removeCurrentEntryCallback(self, bouquet, answer):
		if answer:
			if answer == "never":
				self.confirmRemove = False
			if bouquet:
				self.removeBouquet()
			else:
				self.removeCurrentService()

	def removeCurrentService(self, bouquet=False):
		if self.movemode and self.entry_marked:
			self.toggleMoveMarked() # unmark current entry
		self.editMode = True
		ref = self.servicelist.getCurrent()
		mutableList = self.getMutableList()
		if ref.valid() and mutableList is not None:
			if not mutableList.removeService(ref):
				mutableList.flushChanges() #FIXME dont flush on each single removed service
				self.servicelist.removeCurrent()
				self.servicelist.resetRoot()
				playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
				if not bouquet and playingref and ref == playingref:
					self.channelSelected(doClose=False)

	def addServiceToBouquet(self, dest, service=None):
		mutableList = self.getMutableList(dest)
		if not mutableList is None:
			if service is None: #use current selected service
				service = self.servicelist.getCurrent()
			if not mutableList.addService(service):
				mutableList.flushChanges()
				# do some voodoo to check if current_root is equal to dest
				cur_root = self.getRoot()
				str1 = cur_root and cur_root.toString() or -1
				str2 = dest.toString()
				pos1 = str1.find("FROM BOUQUET")
				pos2 = str2.find("FROM BOUQUET")
				if pos1 != -1 and pos2 != -1 and str1[pos1:] == str2[pos2:]:
					self.servicelist.addService(service)
				self.servicelist.resetRoot()

	def toggleMoveMode(self, select=False):
		self.editMode = True
		if self.movemode:
			if self.entry_marked:
				self.toggleMoveMarked() # unmark current entry
			self.movemode = False
			self.mutableList.flushChanges() # FIXME add check if changes was made
			self.mutableList = None
			self.functiontitle = ""
			self.compileTitle()
			self.saved_title = None
			self.servicelist.resetRoot()
			self.servicelist.l.setHideNumberMarker(config.usage.hide_number_markers.value)
			self.setCurrentSelection(self.servicelist.getCurrent())
		else:
			self.mutableList = self.getMutableList()
			self.movemode = True
			select and self.toggleMoveMarked()
			self.saved_title = self.getTitle()
			self.functiontitle = ' ' + _("[move mode]")
			self.compileTitle()
			self.servicelist.l.setHideNumberMarker(False)
			self.setCurrentSelection(self.servicelist.getCurrent())
		self["Service"].editmode = True

	def handleEditCancel(self):
		if self.movemode: #movemode active?
			self.toggleMoveMode() # disable move mode
		elif self.bouquet_mark_edit != OFF:
			self.endMarkedEdit(True) # abort edit mode

	def toggleMoveMarked(self):
		if self.entry_marked:
			self.servicelist.setCurrentMarked(False)
			self.entry_marked = False
			self.pathChangeDisabled = False # re-enable path change
		else:
			self.servicelist.setCurrentMarked(True)
			self.entry_marked = True
			self.pathChangeDisabled = True # no path change allowed in movemod

	def doContext(self):
		self.session.openWithCallback(self.exitContext, ChannelContextMenu, self)

	def exitContext(self, close=False):
		l = self["list"]
		l.setFontsize()
		l.setItemsPerPage()
		# l.setMode("MODE_TV") # disabled because there is something wrong
		# l.setMode("MODE_TV") automatically sets "hide number marker" to
		# the config.usage.hide_number_markers.value so when we are in "move mode"
		# we need to force display of the markers here after l.setMode("MODE_TV")
		# has run. If l.setMode("MODE_TV") were ever removed above,
		# "self.servicelist.setHideNumberMarker(False)" could be moved
		# directly to the "else" clause of "def toggleMoveMode".
		if self.movemode:
			self.servicelist.setHideNumberMarker(False)
		if close:
			self.cancel()


MODE_TV = 0
MODE_RADIO = 1

subservices_tv_ref = eServiceReference(eServiceReference.idDVB, eServiceReference.flagDirectory)
subservices_tv_ref.setPath("FROM BOUQUET \"groupedservices.virtualsubservices.tv\"")

service_types_tv = service_types_tv_ref.toString()
service_types_radio = service_types_radio_ref.toString()

multibouquet_tv_ref = eServiceReference(service_types_tv_ref)
multibouquet_tv_ref.setPath("FROM BOUQUET \"bouquets.tv\" ORDER BY bouquet")

singlebouquet_tv_ref = serviceRefAppendPath(service_types_tv_ref, " FROM BOUQUET \"userbouquet.favourites.tv\" ORDER BY bouquet")

multibouquet_radio_ref = eServiceReference(service_types_radio_ref)
multibouquet_radio_ref.setPath("FROM BOUQUET \"bouquets.radio\" ORDER BY bouquet")

singlebouquet_radio_ref = serviceRefAppendPath(service_types_radio_ref, " FROM BOUQUET \"userbouquet.favourites.radio\" ORDER BY bouquet")


class ChannelSelectionBase(Screen):
	def __init__(self, session):
		def leftHelp():
			return _("Move to previous marker") if self.servicelist.isVertical() else _("Move to the previous item")

		def rightHelp():
			return _("Move to next marker") if self.servicelist.isVertical() else _("Move to the next item")
		Screen.__init__(self, session)
		self["key_red"] = Button(_("All"))
		self["key_green"] = Button(_("Satellites"))
		self["key_yellow"] = Button(_("Provider"))
		self["key_blue"] = Button(_("Favourites"))

		self["list"] = ServiceListLegacy(self) if config.channelSelection.screenStyle.value == "" or config.channelSelection.widgetStyle.value == "" else ServiceList(self)
		self.servicelist = self["list"]

		self.numericalTextInput = NumericalTextInput(handleTimeout=False)
		self.numericalTextInput.setUseableChars('1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ')

		self.servicePathTV = []
		self.servicePathRadio = []
		self.servicePath = []
		self.history = []
		self.rootChanged = False
		self.startRoot = None
		self.selectionNumber = ""
		self.clearNumberSelectionNumberTimer = eTimer()
		self.clearNumberSelectionNumberTimer.callback.append(self.clearNumberSelectionNumber)
		self.protectContextMenu = True

		self.mode = MODE_TV
		self.dopipzap = False
		self.pathChangeDisabled = False
		self.movemode = False
		self.showSatDetails = False

		self["channelSelectBaseActions"] = HelpableNumberActionMap(self, ["ColorActions", "NumberActions", "InputAsciiActions"],
			{
				"red": (self.showAllServices, _("Show all available services")),
				"green": (boundFunction(self.showSatellites, changeMode=True), _("Show list of transponders")),
				"yellow": (self.showProviders, _("Show list of providers")),
				"blue": (self.showFavourites, _("Show list of bouquets")),
				"gotAsciiCode": self.keyAsciiCode,
				"keyLeft": self.keyLeft,
				"keyRight": self.keyRight,
				"keyRecord": self.keyRecord,
				"1": self.keyNumberGlobal,
				"2": self.keyNumberGlobal,
				"3": self.keyNumberGlobal,
				"4": self.keyNumberGlobal,
				"5": self.keyNumberGlobal,
				"6": self.keyNumberGlobal,
				"7": self.keyNumberGlobal,
				"8": self.keyNumberGlobal,
				"9": self.keyNumberGlobal,
				"0": self.keyNumber0
			}, -2)
		self["legacyNavigationActions"] = HelpableActionMap(self, ["NavigationActions", "PreviousNextActions"], {
			"pageUp": (self.nextBouquet, _("Move to next bouquet")),
			"previous": (self.prevMarker, _("Move to previous marker")),
			"left": (self.servicelist.goLeft, _("Move up a screen / Move to previous item")),
			"right": (self.servicelist.goRight, _("Move down a screen / Move to next item")),
			"next": (self.nextMarker, _("Move to next marker")),
			"pageDown": (self.prevBouquet, _("Move to previous bouquet"))
		}, prio=0, description=_("Channel Selection Navigation Actions"))
		self["newNavigationActions"] = HelpableActionMap(self, ["NavigationActions"], {
			"pageUp": (self.servicelist.goPageUp, _("Move up a screen")),
			"first": (self.prevBouquet, _("Move to previous bouquet")),
			"left": (self.moveLeft, leftHelp),
			"right": (self.moveRight, rightHelp),
			"last": (self.nextBouquet, _("Move to next bouquet")),
			"pageDown": (self.servicelist.goPageDown, _("Move down a screen"))
		}, prio=0, description=_("Channel Selection Navigation Actions"))
		if "keymap.ntr" in config.usage.keymap.value:
			self["legacyNavigationActions"].setEnabled(False)
			self["newNavigationActions"].setEnabled(False)
			self["neutrinoNavigationActions"] = HelpableActionMap(self, ["NavigationActions", "PreviousNextActions"], {
				"pageUp": (self.servicelist.goPageUp, _("Move up a screen")),
				"previous": (self.prevMarker, _("Move to previous marker")),
				"right": (self.nextBouquet, _("Move to next bouquet")),
				"left": (self.prevBouquet, _("Move to previous bouquet")),
				"next": (self.nextMarker, _("Move to next marker")),
				"pageDown": (self.servicelist.goPageDown, _("Move down a screen"))
			}, prio=0, description=_("Channel Selection Navigation Actions"))
		self.maintitle = _("Channel selection")
		self.modetitle = ""
		self.servicetitle = ""
		self.functiontitle = ""
		self.recallBouquetMode()
		self.instanceInfoBarSubserviceSelection = None

	def compileTitle(self):
		self.setTitle(f"{self.maintitle}{self.modetitle}{self.functiontitle}{self.servicetitle}")

	def getBouquetNumOffset(self, bouquet):
		if not config.usage.multibouquet.value:
			return 0
		str = bouquet.toString()
		offset = 0
		if 'userbouquet.' in bouquet.toCompareString():
			serviceHandler = eServiceCenter.getInstance()
			servicelist = serviceHandler.list(bouquet)
			if not servicelist is None:
				while True:
					serviceIterator = servicelist.getNext()
					if not serviceIterator.valid(): #check if end of list
						break
					number = serviceIterator.getChannelNum()
					if number > 0:
						offset = number - 1
						break
		return offset

	def recallBouquetMode(self):
		if self.mode == MODE_TV:
			self.service_types_ref = service_types_tv_ref
			self.bouquet_root = eServiceReference(multibouquet_tv_ref if config.usage.multibouquet.value else singlebouquet_tv_ref)
		else:
			self.service_types_ref = service_types_radio_ref
			self.bouquet_root = eServiceReference(multibouquet_radio_ref if config.usage.multibouquet.value else singlebouquet_radio_ref)
		self.service_types = self.service_types_ref.toString()
		self.bouquet_rootstr = self.bouquet_root.toString()

	def setTvMode(self):
		self.mode = MODE_TV
		self.servicePath = self.servicePathTV
		self.recallBouquetMode()
		self.modetitle = _(" (TV)")
		self.compileTitle()

	def setRadioMode(self):
		self.mode = MODE_RADIO
		self.servicePath = self.servicePathRadio
		self.recallBouquetMode()
		self.modetitle = _(" (Radio)")
		self.compileTitle()

	def setRoot(self, root, justSet=False):
		if self.startRoot is None:
			self.startRoot = self.getRoot()
		path = root.getPath()
		isBouquet = 'FROM BOUQUET' in path and (root.flags & eServiceReference.isDirectory)
		inBouquetRootList = 'FROM BOUQUET "bouquets.' in path #FIXME HACK
		if not inBouquetRootList and isBouquet:
			self.servicelist.setMode(ServiceList.MODE_FAVOURITES)
		else:
			self.servicelist.setMode(ServiceList.MODE_NORMAL)
		self.servicelist.setRoot(root, justSet)
		self.rootChanged = True
		self.buildTitleString()

	def getServiceName(self, serviceReference):
		serviceNameTmp = ServiceReference(serviceReference).getServiceName()
		serviceName = serviceNameTmp.replace(_("(TV)") if self.mode == MODE_TV else _("(Radio)"), "").replace("  ", " ").strip()
		print(f"[ChannelSelection] getServiceName DEBUG: Service Name Before='{serviceNameTmp}', After='{serviceName}'.")
		if "bouquets" in serviceName.lower():
			return _("User bouquets")
		if not serviceName:
			servicePath = serviceReference.getPath()
			if "FROM PROVIDERS" in servicePath:
				return _("Providers")
			if "FROM SATELLITES" in servicePath:
				return _("Satellites")
			if "ORDER BY name" in servicePath:
				return _("All Services")
			if self.isSubservices(serviceReference):
				return _("Subservices")
		elif serviceName == "favourites" and not config.usage.multibouquet.value:  # Translate single bouquet favourites
			return _("Bouquets")
		return serviceName

	def buildTitleString(self):
		self.servicetitle = ""
		pathlen = len(self.servicePath)
		if pathlen > 0:
			self.servicetitle = " - %s" % self.getServiceName(self.servicePath[0])
			if pathlen > 1:
				self.servicetitle += '/'
				if pathlen > 2:
					self.servicetitle += '../'
				self.servicetitle += self.getServiceName(self.servicePath[pathlen - 1])
		self.compileTitle()

	def moveTop(self):  # This is used by InfoBarGenerics.
		self.servicelist.goTop()

	def moveUp(self):  # This is used by InfoBarGenerics.
		if self.servicelist.isVertical():
			self.servicelist.goLineUp()
		else:
			self.servicelist.goLeft()

	def moveLeft(self):
		if self.servicelist.isVertical():
			self.prevMarker()
		else:
			self.servicelist.goLeft()

	def moveRight(self):
		if self.servicelist.isVertical():
			self.nextMarker()
		else:
			self.servicelist.goRight()

	def moveDown(self):  # This is used by InfoBarGenerics.
		if self.servicelist.isVertical():
			self.servicelist.goLineDown()
		else:
			self.servicelist.goRight()

	def moveEnd(self):  # This is used by InfoBarGenerics.
		self.servicelist.goBottom()

	def clearPath(self):
		del self.servicePath[:]

	def enterPath(self, ref, justSet=False):
		self.servicePath.append(ref)
		self.setRoot(ref, justSet)

	def enterUserbouquet(self, root, save_root=True):
		self.clearPath()
		self.recallBouquetMode()
		if self.bouquet_root:
			self.enterPath(self.bouquet_root)
		self.enterPath(root)
		self.startRoot = None
		if save_root:
			self.saveRoot()

	def pathUp(self, justSet=False):
		prev = self.servicePath.pop()
		if self.servicePath:
			current = self.servicePath[-1]
			self.setRoot(current, justSet)
			if not justSet:
				self.setCurrentSelection(prev)
		return prev

	def isBasePathEqual(self, ref):
		if len(self.servicePath) > 1 and self.servicePath[0] == ref:
			return True
		return False

	def isPrevPathEqual(self, ref):
		length = len(self.servicePath)
		if length > 1 and self.servicePath[length - 2] == ref:
			return True
		return False

	def preEnterPath(self, refstr):
		return False

	def showAllServices(self):
		if not self.pathChangeDisabled:
			ref = serviceRefAppendPath(self.service_types_ref, "ORDER BY name")
			if not self.preEnterPath(ref.toString()):
				currentRoot = self.getRoot()
				if currentRoot is None or currentRoot != ref:
					self.clearPath()
					self.enterPath(ref)
					playingref = self.session.nav.getCurrentlyPlayingServiceReference()
					if playingref:
						self.setCurrentSelectionAlternative(playingref)

	def showSatellites(self, changeMode=False):
		if not self.pathChangeDisabled:
			ref = serviceRefAppendPath(self.service_types_ref, "FROM SATELLITES ORDER BY satellitePosition")
			if not self.preEnterPath(ref.toString()):
				justSet = False
				prev = None
				if self.isBasePathEqual(ref):
					if self.isPrevPathEqual(ref):
						justSet = True
					prev = self.pathUp(justSet)
				else:
					currentRoot = self.getRoot()
					if currentRoot is None or currentRoot != ref:
						justSet = True
						self.clearPath()
						self.enterPath(ref, True)
					if changeMode and currentRoot and currentRoot == ref:
						self.showSatDetails = not self.showSatDetails
						justSet = True
						self.clearPath()
						self.enterPath(ref, True)
				if justSet:
					addCableAndTerrestrialLater = []
					serviceHandler = eServiceCenter.getInstance()
					servicelist = serviceHandler.list(ref)
					if not servicelist is None:
						while True:
							service = servicelist.getNext()
							if not service.valid():  # Check if end of list.
								break
							unsigned_orbpos = service.getUnsignedData(4) >> 16
							orbpos = service.getData(4) >> 16
							if orbpos < 0:
								orbpos += 3600
							if "FROM PROVIDER" in service.getPath():
								service_type = self.showSatDetails and _("Providers")
							elif (f"flags == {FLAG_SERVICE_NEW_FOUND}") in service.getPath():
								service_type = self.showSatDetails and _("New")
							else:
								service_type = _("Services")
							if service_type:
								if unsigned_orbpos == 0xFFFF:  # Cable.
									service_name = _("Cable")
									addCableAndTerrestrialLater.append((f"{service_name} - {service_type}", service.toString()))
								elif unsigned_orbpos == 0xEEEE:  # Terrestrial.
									service_name = _("Terrestrial")
									addCableAndTerrestrialLater.append((f"{service_name} - {service_type}", service.toString()))
								else:
									try:
										service_name = str(nimmanager.getSatDescription(orbpos))
									except Exception:
										if orbpos > 1800:  # West.
											orbpos = 3600 - orbpos
											h = _("W")
										else:
											h = _("E")
										service_name = f"{orbpos // 10}.{orbpos % 10}{h}"
									service.setName(f"{service_name} - {service_type}")
									self.servicelist.addService(service)
						cur_ref = self.session.nav.getCurrentlyPlayingServiceReference()
						self.servicelist.sort()
						if cur_ref:
							# pos = self.service_types.rfind(":")  # DEBUG NOTE: This doesn't appear to be used.
							ref = eServiceReference(self.service_types_ref)
							path = '(channelID == %08x%04x%04x) && %s ORDER BY name' % (
								cur_ref.getUnsignedData(4),  # NAMESPACE
								cur_ref.getUnsignedData(2),  # TSID
								cur_ref.getUnsignedData(3),  # ONID
								self.service_types_ref.getPath())
							ref.setPath(path)
							ref.setName(_("Current transponder"))
							self.servicelist.addService(ref, beforeCurrent=True)
							if self.getSubservices():  # Add subservices selection if available.
								ref = eServiceReference(subservices_tv_ref)
								ref.setName(self.getServiceName(ref))
								self.servicelist.addService(ref, beforeCurrent=True)
						for (service_name, service_ref) in addCableAndTerrestrialLater:
							ref = eServiceReference(service_ref)
							ref.setName(service_name)
							self.servicelist.addService(ref, beforeCurrent=True)
						self.servicelist.fillFinished()
						if prev is not None:
							self.setCurrentSelection(prev)
						elif cur_ref:
							op = cur_ref.getUnsignedData(4)
							if op >= 0xffff:
								hop = op >> 16
								if op >= 0x10000000 and (op & 0xffff):
									op &= 0xffff0000
								path = f"(satellitePosition == {hop}) && {self.service_types_ref.getPath()} ORDER BY name"
								ref = eServiceReference(eServiceReference.idDVB, eServiceReference.flagDirectory, path)
								ref.setUnsignedData(4, op)
								self.setCurrentSelectionAlternative(ref)

	def showProviders(self):
		if not self.pathChangeDisabled:
			ref = serviceRefAppendPath(self.service_types_ref, " FROM PROVIDERS ORDER BY name")
			if not self.preEnterPath(ref.toString()):
				if self.isBasePathEqual(ref):
					self.pathUp()
				else:
					currentRoot = self.getRoot()
					if currentRoot is None or currentRoot != ref:
						self.clearPath()
						self.enterPath(ref)
						service = self.session.nav.getCurrentService()
						if service:
							info = service.info()
							if info:
								provider = info.getInfoString(iServiceInformation.sProvider)
								ref = eServiceReference(eServiceReference.idDVB, eServiceReference.flagDirectory)
								ref.setPath("(provider == \"%s\") && %s ORDER BY name" % (provider, self.service_types_ref.getPath()))
								ref.setName(provider)
								self.setCurrentSelectionAlternative(ref)

	def changeBouquet(self, direction):
		if not self.pathChangeDisabled:
			if len(self.servicePath) > 1:
				#when enter satellite root list we must do some magic stuff..
				ref = serviceRefAppendPath(self.service_types_ref, " FROM SATELLITES ORDER BY satellitePosition")
				if self.isBasePathEqual(ref):
					self.showSatellites()
				else:
					self.pathUp()
				if direction < 0:
					self.moveUp()
				else:
					self.moveDown()
				ref = self.getCurrentSelection()
				if not self.getMutableList() or Components.ParentalControl.parentalControl.isServicePlayable(ref, self.changeBouquetParentalControlCallback, self.session):
					self.changeBouquetParentalControlCallback(ref)

	def changeBouquetParentalControlCallback(self, ref):
		self.enterPath(ref)
		self.revertMode = None
		if config.usage.changebouquet_set_history.value and self.shown:
			live_ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			pip_ref = hasattr(self.session, "pip") and self.session.pip.getCurrentService()
			dopipzap = hasattr(self, "dopipzap") and self.dopipzap
			if live_ref and not pip_ref and not dopipzap:
				if live_ref and self.servicelist.setCurrent(live_ref, adjust=False) is None:
					return
			elif live_ref and pip_ref and not dopipzap:
				if live_ref and self.servicelist.setCurrent(live_ref, adjust=False) is None:
					return
			elif dopipzap:
				if pip_ref and self.servicelist.setCurrent(pip_ref, adjust=False) is None:
					return
				elif live_ref and self.servicelist.setCurrent(live_ref, adjust=False) is None:
					return
			root = self.getRoot()
			prev = None
			for path in self.history:
				if len(path) > 2 and path[1] == root:
					prev = path[2]
			if prev is not None:
				self.setCurrentSelection(prev)

	def inBouquet(self):
		if self.servicePath and self.servicePath[0] == self.bouquet_root:
			return True
		return False

	def atBegin(self):
		return self.servicelist.atBegin()

	def atEnd(self):
		return self.servicelist.atEnd()

	def nextBouquet(self):
		if self.shown and config.usage.oldstyle_channel_select_controls.value:
			self.servicelist.instance.moveSelection(self.servicelist.instance.pageUp)
		elif "reverseB" in config.usage.servicelist_cursor_behavior.value:
			self.changeBouquet(-1)
		else:
			self.changeBouquet(+1)

	def prevBouquet(self):
		if self.shown and config.usage.oldstyle_channel_select_controls.value:
			self.servicelist.instance.moveSelection(self.servicelist.instance.pageDown)
		elif "reverseB" in config.usage.servicelist_cursor_behavior.value:
			self.changeBouquet(+1)
		else:
			self.changeBouquet(-1)

	def keyLeft(self):
		if config.usage.oldstyle_channel_select_controls.value:
			self.changeBouquet(-1)
		else:
			self.servicelist.instance.moveSelection(self.servicelist.instance.pageUp)

	def keyRight(self):
		if config.usage.oldstyle_channel_select_controls.value:
			self.changeBouquet(+1)
		else:
			self.servicelist.instance.moveSelection(self.servicelist.instance.pageDown)

	def keyRecord(self):
		ref = self.getCurrentSelection()
		if ref and not (ref.flags & (eServiceReference.isMarker | eServiceReference.isDirectory)):
			Screens.InfoBar.InfoBar.instance.instantRecord(serviceRef=ref)

	def showFavourites(self):
		if not self.pathChangeDisabled:
			if not self.preEnterPath(self.bouquet_root.toString()):
				if self.isBasePathEqual(self.bouquet_root):
					self.pathUp()
				else:
					currentRoot = self.getRoot()
					if currentRoot is None or currentRoot != self.bouquet_root:
						self.clearPath()
						self.enterPath(self.bouquet_root)
						if not config.usage.multibouquet.value:
							playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
							if playingref:
								self.setCurrentSelectionAlternative(playingref)

	def keyNumber0(self, number):
		if self.selectionNumber:
			self.keyNumberGlobal(number)
		elif len(self.servicePath) > 1:
			self.keyGoUp()
		else:
			return False

	def keyNumberGlobal(self, number):
		if self.isBasePathEqual(self.bouquet_root):
			if hasattr(self, "editMode") and self.editMode:
				if number == 2:
					self.renameEntry()
				if number == 6:
					self.toggleMoveMode(select=True)
				if number == 8:
					self.removeCurrentEntry(bouquet=False)
			else:
				self.numberSelectionActions(number)
		else:
			current_root = self.getRoot()
			if current_root and 'FROM BOUQUET "bouquets.' in current_root.getPath():
				if hasattr(self, "editMode") and self.editMode:
					if number == 2:
						self.renameEntry()
					if number == 6:
						self.toggleMoveMode(select=True)
					if number == 8:
						self.removeCurrentEntry(bouquet=True)
				else:
					self.numberSelectionActions(number)
			else:
				unichar = self.numericalTextInput.getKey(number)
				if len(unichar) == 1:
					self.servicelist.moveToChar(unichar[0])

	def numberSelectionActions(self, number):
		if not (hasattr(self, "movemode") and self.movemode):
			if len(self.selectionNumber) > 4:
				self.clearNumberSelectionNumber()
			self.selectionNumber = self.selectionNumber + str(number)
			ref, bouquet = Screens.InfoBar.InfoBar.instance.searchNumber(int(self.selectionNumber), bouquet=self.getRoot())
			if ref:
				if not ref.flags & eServiceReference.isMarker:
					self.enterUserbouquet(bouquet, save_root=False)
					self.setCurrentSelection(ref)
				self.clearNumberSelectionNumberTimer.start(1000, True)
			else:
				self.clearNumberSelectionNumber()

	def clearNumberSelectionNumber(self):
		self.clearNumberSelectionNumberTimer.stop()
		self.selectionNumber = ""

	def keyAsciiCode(self):
		unichar = chr(getPrevAsciiCode())
		if len(unichar) == 1:
			self.servicelist.moveToChar(unichar[0])

	def getRoot(self):
		return self.servicelist.getRoot()

	def getCurrentSelection(self):
		return self.servicelist.getCurrent()

	def setCurrentSelection(self, service):
		if service:
			self.servicelist.setCurrent(service, adjust=False)

	def setCurrentSelectionAlternative(self, ref):
		if self.bouquet_mark_edit == EDIT_ALTERNATIVES and not (ref.flags & eServiceReference.isDirectory):
			for markedService in self.servicelist.getMarked():
				markedService = eServiceReference(markedService)
				self.setCurrentSelection(markedService)
				if markedService == self.getCurrentSelection():
					return
		self.setCurrentSelection(ref)

	def getBouquetList(self):
		bouquets = []
		if self.isSubservices():
			bouquets.append((self.getServiceName(subservices_tv_ref), subservices_tv_ref))
		serviceHandler = eServiceCenter.getInstance()
		if config.usage.multibouquet.value:
			list = serviceHandler.list(self.bouquet_root)
			if list:
				while True:
					s = list.getNext()
					if not s.valid():
						break
					if s.flags & eServiceReference.isDirectory and not s.flags & eServiceReference.isInvisible:
						info = serviceHandler.info(s)
						if info:
							bouquets.append((info.getName(s), s))
				return bouquets
		else:
			info = serviceHandler.info(self.bouquet_root)
			if info:
				bouquets.append((info.getName(self.bouquet_root), self.bouquet_root))
			return bouquets
		return None

	def keyGoUp(self):
		if len(self.servicePath) > 1:
			if self.isBasePathEqual(self.bouquet_root):
				self.showFavourites()
			else:
				ref = serviceRefAppendPath(self.service_types_ref, " FROM SATELLITES ORDER BY satellitePosition")
				if self.isBasePathEqual(ref):
					self.showSatellites()
				else:
					ref = serviceRefAppendPath(self.service_types_ref, " FROM PROVIDERS ORDER BY name")
					if self.isBasePathEqual(ref):
						self.showProviders()
					else:
						self.showAllServices()

	def nextMarker(self):
		self.servicelist.moveToNextMarker()

	def prevMarker(self):
		self.servicelist.moveToPrevMarker()

	def gotoCurrentServiceOrProvider(self, ref):
		if _("Providers") in ref.getName():
			service = self.session.nav.getCurrentService()
			if service:
				info = service.info()
				if info:
					provider = info.getInfoString(iServiceInformation.sProvider)
					op = self.session.nav.getCurrentlyPlayingServiceOrGroup().getUnsignedData(4) >> 16
					ref = eServiceReference(eServiceReference.idDVB, eServiceReference.flagDirectory)
					ref.setPath("(provider == \"%s\") && (satellitePosition == %d) && %s ORDER BY name" % (provider, op, self.service_types_ref.getPath()))
					ref.setName(provider)
					self.servicelist.setCurrent(eServiceReference(ref))
		elif not self.isBasePathEqual(self.bouquet_root) or self.bouquet_mark_edit == EDIT_ALTERNATIVES or (self.startRoot and self.startRoot != ref):
			playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if playingref:
				self.setCurrentSelectionAlternative(playingref)

	def enterSubservices(self, service=None, subservices=[]):
		subservices = subservices or self.getSubservices(service)
		if subservices:
			self.clearPath()
			self.enterPath(subservices_tv_ref)
			self.fillVirtualSubservices(service, subservices)

	def getSubservices(self, service=None):
		if not service:
			service = self.session.nav.getCurrentlyPlayingServiceReference()
		if self.instanceInfoBarSubserviceSelection is None:
			from Screens.InfoBarGenerics import instanceInfoBarSubserviceSelection  # This must be here as the class won't be initialized at module load time.
			self.instanceInfoBarSubserviceSelection = instanceInfoBarSubserviceSelection
		if self.instanceInfoBarSubserviceSelection:
			subserviceGroups = self.instanceInfoBarSubserviceSelection.getSubserviceGroups()
			if subserviceGroups and service:
				refstr = service.toCompareString()
				if "%3a" in refstr:
					refstr = service.toString()
				ref_in_subservices_group = [x for x in subserviceGroups if refstr in x]
				if ref_in_subservices_group:
					return ref_in_subservices_group[0]
		return []

	def fillVirtualSubservices(self, service=None, subservices=[]):
		self.servicelist.setMode(ServiceList.MODE_NORMAL)  # No numbers
		for subservice in subservices or self.getSubservices(service):
			self.servicelist.addService(eServiceReference(subservice))
		# self.servicelist.sort()
		self.setCurrentSelection(service or self.session.nav.getCurrentlyPlayingServiceReference())

	def isSubservices(self, path=None):
		return subservices_tv_ref == (path or self.getRoot() or eServiceReference())

	def getMutableList(self, root=eServiceReference()):  # Override for subservices
		# ChannelContextMenu.inBouquet = True --> Wrong menu
		if self.isSubservices():
			return None
		return ChannelSelectionEdit.getMutableList(self, root)

HISTORYSIZE = 20

#config for lastservice
config.tv = ConfigSubsection()
config.tv.lastservice = ConfigText()
config.tv.lastroot = ConfigText()
config.radio = ConfigSubsection()
config.radio.lastservice = ConfigText()
config.radio.lastroot = ConfigText()
config.servicelist = ConfigSubsection()
config.servicelist.lastmode = ConfigText(default="tv")
config.servicelist.startupservice = ConfigText()
config.servicelist.startupservice_onstandby = ConfigYesNo(default=False)
config.servicelist.startuproot = ConfigText()
config.servicelist.startupmode = ConfigText(default="tv")


class ChannelSelection(ChannelSelectionBase, ChannelSelectionEdit, ChannelSelectionEPG, SelectionEventInfo):

	def __init__(self, session):
		ChannelSelectionBase.__init__(self, session)
		if config.channelSelection.screenStyle.value:
			self.skinName = [config.channelSelection.screenStyle.value]
		ChannelSelectionEdit.__init__(self)
		ChannelSelectionEPG.__init__(self)
		SelectionEventInfo.__init__(self)

		self["actions"] = ActionMap(["OkCancelActions", "TvRadioActions"],
			{
				"cancel": self.cancel,
				"ok": self.channelSelected,
				"keyRadio": self.doRadioButton,
				"keyTV": self.doTVButton,
				"toggleTvRadio": self.toggleTVRadio,
			})

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap={
				iPlayableService.evStart: self.__evServiceStart,
				iPlayableService.evEnd: self.__evServiceEnd
			})

		self.startServiceRef = None

		self.history = []
		self.history_pos = 0
		self.delhistpoint = None

		if config.servicelist.startupservice.value and config.servicelist.startuproot.value:
			config.servicelist.lastmode.value = config.servicelist.startupmode.value
			if config.servicelist.lastmode.value == "tv":
				config.tv.lastservice.value = config.servicelist.startupservice.value
				config.tv.lastroot.value = config.servicelist.startuproot.value
			elif config.servicelist.lastmode.value == "radio":
				config.radio.lastservice.value = config.servicelist.startupservice.value
				config.radio.lastroot.value = config.servicelist.startuproot.value

		self.lastservice = config.tv.lastservice
		self.lastroot = config.tv.lastroot
		self.revertMode = None
		config.usage.multibouquet.addNotifier(self.multibouquet_config_changed)
		self.new_service_played = False
		self.dopipzap = False
		self.onExecBegin.append(self.asciiOn)
		self.mainScreenMode = None
		self.mainScreenRoot = None

		self.lastChannelRootTimer = eTimer()
		self.lastChannelRootTimer.callback.append(self.__onCreate)
		self.lastChannelRootTimer.start(100, True)
		self.pipzaptimer = eTimer()
		self.session.onShutdown.append(self.close)

	def __del__(self):
		self.session.onShutdown.remove(self.close)

	def asciiOn(self):
		rcinput = eRCInput.getInstance()
		rcinput.setKeyboardMode(rcinput.kmAscii)

	def asciiOff(self):
		rcinput = eRCInput.getInstance()
		rcinput.setKeyboardMode(rcinput.kmNone)

	def multibouquet_config_changed(self, val):
		self.recallBouquetMode()

	def __evServiceStart(self):
		if self.dopipzap and hasattr(self.session, 'pip'):
			self.servicelist.setPlayableIgnoreService(self.session.pip.getCurrentServiceReference() or eServiceReference())
		else:
			service = self.session.nav.getCurrentService()
			if service:
				info = service.info()
				if info:
					refstr = info.getInfoString(iServiceInformation.sServiceref)
					refstr, isStreamRelay = getStreamRelayRef(refstr)
					ref = eServiceReference(refstr)
					if isStreamRelay:
						if not [timer for timer in self.session.nav.RecordTimer.timer_list if timer.state == 2 and refstr == timer.service_ref]:
							ref.setAlternativeUrl(refstr, True)
					self.servicelist.setPlayableIgnoreService(ref)

	def __evServiceEnd(self):
		self.servicelist.setPlayableIgnoreService(eServiceReference())

	def setMode(self):
		self.rootChanged = True
		self.restoreRoot()
		lastservice = eServiceReference(self.lastservice.value)
		if lastservice.valid():
			if self.isSubservices():
				self.enterSubservices(lastservice)
			self.setCurrentSelection(lastservice)
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if ref and Components.ParentalControl.parentalControl.isProtected(ref):
				if self.getCurrentSelection() and self.getCurrentSelection() != ref:
					self.setCurrentSelection(ref)

	def doTVButton(self):
		if self.mode == MODE_TV:
			self.channelSelected(doClose=False)
		else:
			self.setModeTv()

	def setModeTv(self):
		if self.revertMode is None:
			self.revertMode = self.mode
		self.lastservice = config.tv.lastservice
		self.lastroot = config.tv.lastroot
		config.servicelist.lastmode.value = "tv"
		self.setTvMode()
		self.setMode()

	def doRadioButton(self):
		if self.mode == MODE_RADIO:
			self.channelSelected(doClose=False)
		else:
			self.setModeRadio()

	def setModeRadio(self):
		if self.revertMode is None:
			self.revertMode = self.mode
		if config.usage.e1like_radio_mode.value:
			self.lastservice = config.radio.lastservice
			self.lastroot = config.radio.lastroot
			config.servicelist.lastmode.value = "radio"
			self.setRadioMode()
			self.setMode()

	def toggleTVRadio(self):
		if self.mode == MODE_TV:
			self.doRadioButton()
		else:
			self.doTVButton()

	def __onCreate(self):
		if config.usage.e1like_radio_mode.value:
			if config.servicelist.lastmode.value == "tv":
				self.setModeTv()
			else:
				self.setModeRadio()
		else:
			self.setModeTv()
		lastservice = eServiceReference(self.lastservice.value)
		if lastservice.valid():
			if self.isSubservices():
				self.zap(ref=lastservice)
				self.enterSubservices()
			else:
				self.zap()

	def channelSelected(self, doClose=True):
		ref = self.getCurrentSelection()
		if ref.type == -1:
			return
		playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if config.usage.channelselection_preview.value and (playingref is None or self.getCurrentSelection() != playingref):
			doClose = False
		if not self.startServiceRef and not doClose:
			self.startServiceRef = playingref
		if self.movemode and (self.isBasePathEqual(self.bouquet_root) or "userbouquet." in ref.toString()):
			self.toggleMoveMarked()
		elif (ref.flags & eServiceReference.flagDirectory) == eServiceReference.flagDirectory:
			if self.isSubservices(ref):
				self.enterSubservices()
			elif Components.ParentalControl.parentalControl.isServicePlayable(ref, self.bouquetParentalControlCallback, self.session):
				self.enterPath(ref)
				self.gotoCurrentServiceOrProvider(ref)
				self.revertMode = None
		elif self.bouquet_mark_edit != OFF:
			if not (self.bouquet_mark_edit == EDIT_ALTERNATIVES and ref.flags & eServiceReference.isGroup):
				self.doMark()
		elif not ref.flags & eServiceReference.isMarker:
			root = self.getRoot()
			if not root or not (root.flags & eServiceReference.isGroup):
				self.zap(enable_pipzap=doClose, preview_zap=not doClose)
				self.asciiOff()
				if doClose:
					if self.dopipzap:
						self.zapBack()
					self.startServiceRef = None
					self.startRoot = None
					self.correctChannelNumber()
					self.movemode and self.toggleMoveMode()
					self.editMode = False
					self.protectContextMenu = True
					self.close(ref)

	def bouquetParentalControlCallback(self, ref):
		self.enterPath(ref)
		self.gotoCurrentServiceOrProvider(ref)
		self.revertMode = None

	def togglePipzap(self):
		assert (self.session.pip)
		if self.dopipzap:
			# Mark PiP as inactive and effectively deactivate pipzap
			self.hidePipzapMessage()
			self.dopipzap = False

			# Disable PiP if not playing a service
			if self.session.pip.pipservice is None:
				self.session.pipshown = False
				del self.session.pip
			self.__evServiceStart()
			# Move to playing service
			lastservice = eServiceReference(self.lastservice.value)
			ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
			if ref and Components.ParentalControl.parentalControl.isProtected(ref):
				lastservice = ref
			if lastservice.valid() and self.getCurrentSelection() != lastservice:
				self.setCurrentSelection(lastservice)
				if self.getCurrentSelection() != lastservice:
					self.servicelist.setCurrent(lastservice)

			self.modetitle = _(" (TV)")
		else:
			# Mark PiP as active and effectively active pipzap
			self.showPipzapMessage()
			self.dopipzap = True
			self.__evServiceStart()
			# Move to service playing in pip (will not work with subservices)
			self.setCurrentSelection(self.session.pip.getCurrentService())
			self.modetitle = _(" (PiP)")
		self.buildTitleString()

	def showPipzapMessage(self):
		time = config.usage.infobar_timeout.index
		if time:
			self.pipzaptimer.callback.append(self.hidePipzapMessage)
			self.pipzaptimer.startLongTimer(time)
		self.session.pip.active()

	def hidePipzapMessage(self):
		if self.pipzaptimer.isActive():
			self.pipzaptimer.callback.remove(self.hidePipzapMessage)
			self.pipzaptimer.stop()
		self.session.pip.inactive()

	#called from infoBar and channelSelected
	def zap(self, enable_pipzap=False, preview_zap=False, checkParentalControl=True, ref=None):
		self.curRoot = self.startRoot
		nref = ref or self.getCurrentSelection()
		ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if enable_pipzap and self.dopipzap:
			ref = self.session.pip.getCurrentService()
			if ref is None or ref != nref:
				if nref:
					if not checkParentalControl or Components.ParentalControl.parentalControl.isServicePlayable(nref, boundFunction(self.zap, enable_pipzap=True, checkParentalControl=False)):
						self.session.pip.playService(nref)
						self.__evServiceStart()
						self.showPipzapMessage()
						self.setCurrentSelection(nref)
				else:
					self.setStartRoot(self.curRoot)
					self.setCurrentSelection(ref)
		elif ref is None or ref != nref:
			Screens.InfoBar.InfoBar.instance.checkTimeshiftRunning(boundFunction(self.zapCheckTimeshiftCallback, preview_zap, nref))
		elif not preview_zap:
			self.saveRoot()
			self.saveChannel(nref)
			config.servicelist.lastmode.save()
			self.setCurrentSelection(nref)
			if self.startServiceRef is None or nref != self.startServiceRef:
				self.addToHistory(nref)
			self.rootChanged = False
			self.revertMode = None

	def zapCheckTimeshiftCallback(self, preview_zap, nref, answer):
		if answer:
			self.new_service_played = True
			self.session.nav.playService(nref, adjust=preview_zap and [0, self.session] or True)
			if not preview_zap:
				self.saveRoot()
				self.saveChannel(nref)
				config.servicelist.lastmode.save()
				if self.startServiceRef is None or nref != self.startServiceRef:
					self.addToHistory(nref)
				if self.dopipzap:
					self.session.pip.servicePath = self.getCurrentServicePath()
					self.setCurrentSelection(self.session.pip.getCurrentService())
				else:
					self.mainScreenMode = config.servicelist.lastmode.value
					self.mainScreenRoot = self.getRoot()
				self.revertMode = None
			else:
				RemovePopup("Parental control")
				self.setCurrentSelection(nref)
		elif not self.dopipzap:
			self.setStartRoot(self.curRoot)
			self.setCurrentSelection(self.session.nav.getCurrentlyPlayingServiceOrGroup())
		if not preview_zap:
			self.hide()

	def newServicePlayed(self):
		ret = self.new_service_played
		self.new_service_played = False
		return ret

	def addToHistory(self, ref):
		if not self.isSubservices():
			if self.delhistpoint is not None:
				x = self.delhistpoint
				while x <= len(self.history)-1:
					del self.history[x]
			self.delhistpoint = None

			if self.servicePath is not None:
				tmp = self.servicePath[:]
				tmp.append(ref)
				self.history.append(tmp)
				hlen = len(self.history)
				x = 0
				while x < hlen - 1:
					if self.history[x][-1] == ref:
						del self.history[x]
						hlen -= 1
					else:
						x += 1

				if hlen > HISTORYSIZE:
					del self.history[0]
					hlen -= 1
				self.history_pos = hlen - 1

	def historyBack(self):
		hlen = len(self.history)
		currentPlayedRef = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if hlen > 0 and currentPlayedRef and self.history[self.history_pos][-1] != currentPlayedRef:
			self.addToHistory(currentPlayedRef)
			hlen = len(self.history)
		if hlen > 1 and self.history_pos > 0:
			self.history_pos -= 1
			self.setHistoryPath()
		self.delhistpoint = self.history_pos+1

	def historyNext(self):
		self.delhistpoint = None
		hlen = len(self.history)
		if hlen > 1 and self.history_pos < (hlen - 1):
			self.history_pos += 1
			self.setHistoryPath()

	def setHistoryPath(self, doZap=True):
		path = self.history[self.history_pos][:]
		ref = path.pop()
		del self.servicePath[:]
		self.servicePath += path
		self.saveRoot()
		root = path[-1]
		cur_root = self.getRoot()
		if cur_root and cur_root != root:
			self.setRoot(root)
		if doZap:
			self.session.nav.playService(ref, adjust=False)
		if self.dopipzap:
			self.setCurrentSelection(self.session.pip.getCurrentService())
		else:
			self.setCurrentSelection(ref)
		self.saveChannel(ref)

	def historyClear(self):
		if self and self.servicelist:
			for i in range(0, len(self.history)-1):
				del self.history[0]
			self.history_pos = len(self.history)-1
			return True
		return False

	def historyZap(self, direction):
		count = len(self.history)
		if count > 0:
			selectedItem = self.history_pos + direction
			if selectedItem < 0:
				selectedItem = 0
			elif selectedItem > count - 1:
				selectedItem = count - 1
			self.session.openWithCallback(self.historyMenuClosed, HistoryZapSelector, [x[-1] for x in self.history], markedItem=self.history_pos, selectedItem=selectedItem)

	def historyMenuClosed(self, retval):
		if not retval:
			return
		hlen = len(self.history)
		pos = 0
		for x in self.history:
			if x[-1] == retval:
				break
			pos += 1
		self.delhistpoint = pos + 1
		if pos < hlen and pos != self.history_pos:
			tmp = self.history[pos]
			# self.history.append(tmp)
			# del self.history[pos]
			self.history_pos = pos
			self.setHistoryPath()

	def saveRoot(self):
		path = ""
		for i in self.servicePath:
			path += i.toString()
			path += ";"
		if path and path != self.lastroot.value:
			if self.mode == MODE_RADIO and "FROM BOUQUET \"bouquets.tv\"" in path:
				self.setModeTv()
			elif self.mode == MODE_TV and "FROM BOUQUET \"bouquets.radio\"" in path:
				self.setModeRadio()
			self.lastroot.value = path
			self.lastroot.save()
			self.updateBouquetPath(path)

	def restoreRoot(self):
		tmp = [x for x in self.lastroot.value.split(';') if x != '']
		current = [x.toString() for x in self.servicePath]
		if tmp != current or self.rootChanged:
			self.clearPath()
			cnt = 0
			for i in tmp:
				self.servicePath.append(eServiceReference(i))
				cnt += 1
			if cnt:
				path = self.servicePath.pop()
				self.enterPath(path)
				if self.isSubservices(path):
					self.fillVirtualSubservices()
			else:
				self.showFavourites()
				self.saveRoot()
			self.rootChanged = False

	def preEnterPath(self, refstr):
		if self.servicePath and self.servicePath[0] != eServiceReference(refstr):
			pathstr = self.lastroot.value
			if pathstr is not None and refstr in pathstr:
				self.restoreRoot()
				lastservice = eServiceReference(self.lastservice.value)
				if lastservice.valid():
					self.setCurrentSelection(lastservice)
				return True
		return False

	def saveChannel(self, ref):
		if ref is not None:
			refstr = ref.toString()
		else:
			refstr = ""
		if refstr != self.lastservice.value and not Components.ParentalControl.parentalControl.isProtected(ref):
			self.lastservice.value = refstr
			self.lastservice.save()

	def setCurrentServicePath(self, path, doZap=True):
		hlen = len(self.history)
		if not hlen:
			self.history.append(path)
			self.history_pos = 0
		if hlen == 1:
			self.history[self.history_pos] = path
		else:
			if path in self.history:
				self.history.remove(path)
				self.history_pos -= 1
			tmp = self.history[self.history_pos][:]
			self.history.append(tmp)
			self.history_pos += 1
			self.history[self.history_pos] = path
		self.setHistoryPath(doZap)

	def getCurrentServicePath(self):
		if self.history:
			return self.history[self.history_pos]
		return None

	def recallPrevService(self):
		hlen = len(self.history)
		currentPlayedRef = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if hlen > 0 and currentPlayedRef and self.history[self.history_pos][-1] != currentPlayedRef:
			self.addToHistory(currentPlayedRef)
			hlen = len(self.history)
		if hlen > 1:
			if self.history_pos == hlen - 1:
				tmp = self.history[self.history_pos]
				self.history[self.history_pos] = self.history[self.history_pos - 1]
				self.history[self.history_pos - 1] = tmp
			else:
				tmp = self.history[self.history_pos + 1]
				self.history[self.history_pos + 1] = self.history[self.history_pos]
				self.history[self.history_pos] = tmp
			self.setHistoryPath()

	def cancel(self):
		if self.revertMode is None:
			self.restoreRoot()
			if self.dopipzap:
				# This unfortunately won't work with subservices
				self.setCurrentSelection(self.session.pip.getCurrentService())
			else:
				lastservice = eServiceReference(self.lastservice.value)
				ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
				if ref and Components.ParentalControl.parentalControl.isProtected(ref):
					lastservice = ref
				if lastservice.valid() and self.getCurrentSelection() != lastservice:
					self.setCurrentSelection(lastservice)
		elif self.revertMode == MODE_TV and self.mode == MODE_RADIO:
			self.setModeTv()
		elif self.revertMode == MODE_RADIO and self.mode == MODE_TV:
			self.setModeRadio()
		self.asciiOff()
		self.zapBack()
		self.correctChannelNumber()
		self.editMode = False
		self.protectContextMenu = True
		self.close(None)

	def zapBack(self):
		playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if self.startServiceRef and (playingref is None or playingref != self.startServiceRef):
			self.setStartRoot(self.startRoot)
			self.new_service_played = True
			self.session.nav.playService(self.startServiceRef)
			self.saveChannel(self.startServiceRef)
		else:
			self.restoreMode()
		self.startServiceRef = None
		self.startRoot = None
		if self.dopipzap:
			# This unfortunately won't work with subservices
			self.setCurrentSelection(self.session.pip.getCurrentService())
		else:
			lastservice = eServiceReference(self.lastservice.value)
			if lastservice.valid() and self.getCurrentSelection() == lastservice:
				pass	# keep current selection
			else:
				self.setCurrentSelection(playingref)

	def setStartRoot(self, root):
		if root:
			if self.revertMode == MODE_TV:
				self.setModeTv()
			elif self.revertMode == MODE_RADIO:
				self.setModeRadio()
			self.revertMode = None
			self.enterUserbouquet(root)

	def restoreMode(self):
		if self.revertMode == MODE_TV:
			self.setModeTv()
		elif self.revertMode == MODE_RADIO:
			self.setModeRadio()
		self.revertMode = None

	def correctChannelNumber(self):
		current_ref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
		if self.dopipzap:
			tmp_mode = config.servicelist.lastmode.value
			tmp_root = self.getRoot()
			tmp_ref = self.getCurrentSelection()
			pip_ref = self.session.pip.getCurrentService()
			if tmp_ref and pip_ref and tmp_ref != pip_ref:
				self.revertMode = None
				return
			if self.mainScreenMode == "tv":
				self.setModeTv()
			elif self.mainScreenMode == "radio":
				self.setModeRadio()
			if self.mainScreenRoot:
				self.setRoot(self.mainScreenRoot)
				self.setCurrentSelection(current_ref)
		selected_ref = self.getCurrentSelection()
		if selected_ref and current_ref and selected_ref.getChannelNum() != current_ref.getChannelNum():
			oldref = self.session.nav.currentlyPlayingServiceReference
			if oldref and (selected_ref == oldref or (oldref != current_ref and selected_ref == current_ref)):
				self.session.nav.currentlyPlayingServiceOrGroup = selected_ref
				self.session.nav.pnav.navEvent(iPlayableService.evStart)
		if self.dopipzap:
			if tmp_mode == "tv":
				self.setModeTv()
			elif tmp_mode == "radio":
				self.setModeRadio()
			self.enterUserbouquet(tmp_root)
			self.modetitle = _(" (PiP)")
			self.buildTitleString()
			if tmp_ref and pip_ref and tmp_ref.getChannelNum() != pip_ref.getChannelNum():
				self.session.pip.currentService = tmp_ref
			self.setCurrentSelection(tmp_ref)
		self.revertMode = None


class RadioInfoBar(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		self["RdsDecoder"] = RdsDecoder(self.session.nav)


class ChannelSelectionRadio(ChannelSelectionBase, ChannelSelectionEdit, ChannelSelectionEPG, InfoBarBase, SelectionEventInfo, InfoBarScreenSaver):

	def __init__(self, session, infobar):
		ChannelSelectionBase.__init__(self, session)
		self["list"] = ServiceListLegacy(self)  # Force legacy list
		self.servicelist = self["list"]
		ChannelSelectionEdit.__init__(self)
		ChannelSelectionEPG.__init__(self)
		InfoBarBase.__init__(self)
		SelectionEventInfo.__init__(self)
		InfoBarScreenSaver.__init__(self)
		self.infobar = infobar
		self.startServiceRef = None
		self.onLayoutFinish.append(self.onCreate)

		self.info = session.instantiateDialog(RadioInfoBar) # our simple infobar

		self["key_menu"] = StaticText(_("MENU"))
		self["key_info"] = StaticText(_("INFO"))

		self["actions"] = ActionMap(["OkCancelActions", "TvRadioActions"],
			{
				"keyTV": self.cancel,
				"keyRadio": self.cancel,
				"cancel": self.cancel,
				"ok": self.channelSelected,
				"audio": self.audioSelection
			})

		self.__event_tracker = ServiceEventTracker(screen=self, eventmap={
				iPlayableService.evStart: self.__evServiceStart,
				iPlayableService.evEnd: self.__evServiceEnd
			})

########## RDS Radiotext / Rass Support BEGIN
		self.infobar = infobar # reference to real infobar (the one and only)
		self["RdsDecoder"] = self.info["RdsDecoder"]
		self["rdsActions"] = HelpableActionMap(self, ["InfobarRdsActions"],
		{
			"startRassInteractive": (self.startRassInteractive, _("View Rass interactive..."))
		}, -1)
		self["rdsActions"].setEnabled(False)
		infobar.rds_display.onRassInteractivePossibilityChanged.append(self.RassInteractivePossibilityChanged)
		self.onClose.append(self.__onClose)
		self.onExecBegin.append(self.__onExecBegin)
		self.onExecEnd.append(self.__onExecEnd)

	def __onClose(self):
		lastservice = eServiceReference(config.tv.lastservice.value)
		self.session.nav.playService(lastservice)

	def startRassInteractive(self):
		self.info.hide()
		self.infobar.rass_interactive = self.session.openWithCallback(self.RassInteractiveClosed, RassInteractive)

	def RassInteractiveClosed(self):
		self.info.show()
		self.infobar.rass_interactive = None
		self.infobar.RassSlidePicChanged()

	def RassInteractivePossibilityChanged(self, state):
		self["rdsActions"].setEnabled(state)
########## RDS Radiotext / Rass Support END

	def __onExecBegin(self):
		self.info.show()

	def __onExecEnd(self):
		self.info.hide()

	def cancel(self):
		self.infobar.rds_display.onRassInteractivePossibilityChanged.remove(self.RassInteractivePossibilityChanged)
		self.info.hide()
		#set previous tv service
		self.close(None)

	def __evServiceStart(self):
		service = self.session.nav.getCurrentService()
		if service:
			info = service.info()
			if info:
				refstr = info.getInfoString(iServiceInformation.sServiceref)
				self.servicelist.setPlayableIgnoreService(eServiceReference(refstr))

	def __evServiceEnd(self):
		self.servicelist.setPlayableIgnoreService(eServiceReference())

	def saveRoot(self):
		path = ''
		for i in self.servicePathRadio:
			path += i.toString()
			path += ';'
		if path and path != config.radio.lastroot.value:
			config.radio.lastroot.value = path
			config.radio.lastroot.save()
			self.updateBouquetPath(path)

	def restoreRoot(self):
		tmp = [x for x in config.radio.lastroot.value.split(';') if x != '']
		current = [x.toString() for x in self.servicePath]
		if tmp != current or self.rootChanged:
			cnt = 0
			for i in tmp:
				self.servicePathRadio.append(eServiceReference(i))
				cnt += 1
			if cnt:
				path = self.servicePathRadio.pop()
				self.enterPath(path)
			else:
				self.showFavourites()
				self.saveRoot()
			self.rootChanged = False

	def preEnterPath(self, refstr):
		if self.servicePathRadio and self.servicePathRadio[0] != eServiceReference(refstr):
			pathstr = config.radio.lastroot.value
			if pathstr is not None and refstr in pathstr:
				self.restoreRoot()
				lastservice = eServiceReference(config.radio.lastservice.value)
				if lastservice.valid():
					self.setCurrentSelection(lastservice)
				return True
		return False

	def onCreate(self):
		self.setRadioMode()
		self.restoreRoot()
		lastservice = eServiceReference(config.radio.lastservice.value)
		if lastservice.valid():
			self.servicelist.setCurrent(lastservice)
			if config.usage.e1like_radio_mode_last_play.value:
				self.session.nav.playService(lastservice)
			else:
				self.session.nav.stopService()
		else:
			self.session.nav.stopService()
		self.info.show()

	def channelSelected(self, doClose=False): # just return selected service
		ref = self.getCurrentSelection()
		if self.movemode:
			self.toggleMoveMarked()
		elif (ref.flags & eServiceReference.flagDirectory) == eServiceReference.flagDirectory:
			self.enterPath(ref)
			self.gotoCurrentServiceOrProvider(ref)
		elif self.bouquet_mark_edit != OFF:
			if not (self.bouquet_mark_edit == EDIT_ALTERNATIVES and ref.flags & eServiceReference.isGroup):
				self.doMark()
		elif not (ref.flags & eServiceReference.isMarker): # no marker
			cur_root = self.getRoot()
			if not cur_root or not (cur_root.flags & eServiceReference.isGroup):
				playingref = self.session.nav.getCurrentlyPlayingServiceOrGroup()
				if playingref is None or playingref != ref:
					self.session.nav.playService(ref)
					config.radio.lastservice.value = ref.toString()
					config.radio.lastservice.save()
				self.saveRoot()

	def zapBack(self):
		self.channelSelected()

	def audioSelection(self):
		Screens.InfoBar.InfoBar.instance and Screens.InfoBar.InfoBar.instance.audioSelection()


class SimpleChannelSelection(ChannelSelectionBase, SelectionEventInfo):
	def __init__(self, session, title, currentBouquet=False, returnBouquet=False, setService=None, setBouquet=None):
		ChannelSelectionBase.__init__(self, session)
		self["list"] = ServiceListLegacy(self)  # Force legacy list
		self.servicelist = self["list"]
		SelectionEventInfo.__init__(self)

		self["key_menu"] = StaticText(_("MENU"))
		self["key_info"] = StaticText(_("INFO"))

		self["actions"] = ActionMap(["OkCancelActions", "TvRadioActions"],
			{
				"cancel": self.close,
				"ok": self.channelSelected,
				"epg": self.channelSelected,
				"keyRadio": self.setModeRadio,
				"keyTV": self.setModeTv,
				"toggleTvRadio": self.toggleTVRadio,
			})
		self.bouquet_mark_edit = OFF
		if isinstance(title, str):
			self.maintitle = title
		self.currentBouquet = currentBouquet
		self.returnBouquet = returnBouquet
		self.setService = setService
		self.setBouquet = setBouquet
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self.setModeTv()
		if self.currentBouquet or self.setBouquet:
			ref = self.setBouquet or Screens.InfoBar.InfoBar.instance.servicelist.getRoot()
			if ref:
				self.enterPath(ref)
				self.gotoCurrentServiceOrProvider(ref)
		if self.setService:
			self.setCurrentSelection(self.setService)

	def saveRoot(self):
		pass

	def keyRecord(self):
		return 0

	def channelSelected(self): # just return selected service
		ref = self.getCurrentSelection()
		if (ref.flags & eServiceReference.flagDirectory) == eServiceReference.flagDirectory:
			self.enterPath(ref)
			self.gotoCurrentServiceOrProvider(ref)
		elif not (ref.flags & eServiceReference.isMarker):
			ref = self.getCurrentSelection()
			if self.returnBouquet and len(self.servicePath):
				self.close(ref, self.servicePath[-1])
			else:
				self.close(ref)

	def setModeTv(self):
		self.setTvMode()
		self.showFavourites()

	def setModeRadio(self):
		self.setRadioMode()
		self.showFavourites()

	def toggleTVRadio(self):
		if self.mode == MODE_TV :
			self.setModeRadio()
		else:
			self.setModeTv()

	def getMutableList(self, root=None):
		return None


class HistoryZapSelector(Screen):
	# HISTORY_SPACER = 0
	# HISTORY_MARKER = 1
	# HISTORY_SERVICE_NAME = 2
	# HISTORY_EVENT_NAME = 3
	# HISTORY_EVENT_DESCRIPTION = 4
	# HISTORY_EVENT_DURATION = 5
	# HISTORY_SERVICE_PICON = 6
	HISTORY_SERVICE_REFERENCE = 7

	def __init__(self, session, serviceReferences, markedItem=0, selectedItem=0):
		Screen.__init__(self, session, enableHelp=True)
		self.setTitle(_("History Zap"))
		serviceHandler = eServiceCenter.getInstance()
		historyList = []
		for index, serviceReference in enumerate(serviceReferences):
			info = serviceHandler.info(serviceReference)
			if info:
				serviceName = info.getName(serviceReference) or ""
				eventName = ""
				eventDescription = ""
				eventDuration = ""
				event = info.getEvent(serviceReference)
				if event:
					eventName = event.getEventName() or ""
					eventDescription = event.getShortDescription()
					if not eventDescription:
						eventDescription = event.getExtendedDescription() or ""
					begin = event.getBeginTime()
					if begin:
						end = begin + event.getDuration()
						remaining = (end - int(time())) // 60
						prefix = "+" if remaining > 0 else ""
						localBegin = localtime(begin)
						localEnd = localtime(end)
						eventDuration = f"{strftime(config.usage.time.short.value, localBegin)}  -  {strftime(config.usage.time.short.value, localEnd)}    ({prefix}{ngettext('%d Min', '%d Mins', remaining) % remaining})"
				servicePicon = getPiconName(str(ServiceReference(serviceReference)))
				servicePicon = loadPNG(servicePicon) if servicePicon else ""
				historyList.append(("", index == markedItem and "\u00BB" or "", serviceName, eventName, eventDescription, eventDuration, servicePicon, serviceReference))
		if config.usage.zapHistorySort.value == 0:
			historyList.reverse()
			self.selectedItem = len(historyList) - selectedItem - 1
		else:
			self.selectedItem = selectedItem
		self["menu"] = List(historyList)
		self["key_red"] = StaticText(_("Cancel"))
		self["key_green"] = StaticText(_("Select"))
		self["actions"] = HelpableActionMap(self, ["SelectCancelActions"], {
			"select": (self.keySelect, _("Select the currently highlighted service")),
			"cancel": (self.keyCancel, _("Cancel the service history zap"))
		}, prio=0, description=_("History Zap Actions"))
		previousNext = ("previous", "next") if config.usage.zapHistorySort.value else ("next", "previous")
		self["navigationActions"] = HelpableActionMap(self, ["NavigationActions", "PreviousNextActions"], {
			"left": (self["menu"].goTop, _("Move to the last line / screen")),
			"top": (self["menu"].goTop, _("Move to the first line / screen")),
			"pageUp": (self["menu"].goPageUp, _("Move up a screen")),
			"up": (self["menu"].goLineUp, _("Move up a line")),
			previousNext[0]: (self["menu"].goLineUp, _("Move up a line")),
			previousNext[1]: (self["menu"].goLineDown, _("Move down a line")),
			"down": (self["menu"].goLineDown, _("Move down a line")),
			"pageDown": (self["menu"].goPageDown, _("Move down a screen")),
			"bottom": (self["menu"].goBottom, _("Move to the last line / screen")),
			"right": (self["menu"].goBottom, _("Move to the first line / screen"))
		}, prio=0, description=_("History Zap Navigation Actions"))
		self.onLayoutFinish.append(self.layoutFinished)

	def layoutFinished(self):
		self["menu"].enableAutoNavigation(False)
		self["menu"].setIndex(self.selectedItem)

	def keyCancel(self):
		self.close(None)  # Send None to tell the calling code that the selection was canceled.

	def keySelect(self):
		current = self["menu"].getCurrent()
		self.close(current and current[self.HISTORY_SERVICE_REFERENCE])  # Send the selected ServiceReference to the calling code.


class ChannelSelectionSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session=session, setup="ChannelSelection")
		self.addSaveNotifier(self.onUpdateSettings)
		self.onClose.append(self.clearSaveNotifiers)

	def onUpdateSettings(self):
		ChannelSelectionSetup.updateSettings(self.session)

	@staticmethod
	def updateSettings(session):
		styleChanged = False
		styleScreenChanged = config.channelSelection.screenStyle.isChanged() or config.channelSelection.widgetStyle.isChanged()
		if not styleScreenChanged:
			for setting in ("showNumber", "showPicon", "showServiceTypeIcon", "showCryptoIcon", "recordIndicatorMode", "piconRatio"):
				if getattr(config.channelSelection, setting).isChanged():
					styleChanged = True
					break
			if styleChanged:
				from Screens.InfoBar import InfoBar
				InfoBarInstance = InfoBar.instance
				if InfoBarInstance is not None and InfoBarInstance.servicelist is not None:
					InfoBarInstance.servicelist.servicelist.readTemplate(config.channelSelection.widgetStyle.value)
		else:
			InfoBarInstance = Screens.InfoBar.InfoBar.instance
			if InfoBarInstance is not None and InfoBarInstance.servicelist is not None:
				oldDialogIndex = (-1, None)
				oldSummarys = InfoBarInstance.servicelist.summaries[:]
				for index, dialog in enumerate(session.dialog_stack):
					if isinstance(dialog[0], ChannelSelection):
						oldDialogIndex = (index, dialog[1])
				InfoBarInstance.servicelist = session.instantiateDialog(ChannelSelection)
				InfoBarInstance.servicelist.summaries = oldSummarys
				InfoBarInstance.servicelist.isTmp = False
				InfoBarInstance.servicelist.callback = None
				if oldDialogIndex[0] != -1:
					session.dialog_stack[oldDialogIndex[0]] = (InfoBarInstance.servicelist, oldDialogIndex[1])
