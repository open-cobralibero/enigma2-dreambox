# -*- coding: utf-8 -*-
import os
import time
from Components.config import config

ECM_INFO = '/tmp/ecm.info'
EMPTY_ECM_INFO = '', '0', '0', '0'

old_ecm_time = time.time()
info = {}
ecm = ''
data = EMPTY_ECM_INFO


def getCaidData():
	return (
		("0x100", "0x1ff", "Seca", "S", True),
		("0x500", "0x5ff", "Via", "V", True),
		("0x600", "0x6ff", "Irdeto", "I", True),
		("0x900", "0x9ff", "NDS", "Nd", True),
		("0xb00", "0xbff", "Conax", "Co", True),
		("0xd00", "0xdff", "CryptoW", "Cw", True),
		("0xe00", "0xeff", "PowerVU", "P", False),
		("0x1000", "0x10FF", "Tandberg", "TB", False),
		("0x1700", "0x17ff", "Beta", "B", True),
		("0x1800", "0x18ff", "Nagra", "N", True),
		("0x2600", "0x2600", "Biss", "Bi", False),
		("0x4ae0", "0x4ae1", "Dre", "D", False),
		("0x4aee", "0x4aee", "BulCrypt", "B1", False),
		("0x5581", "0x5581", "BulCrypt", "B2", False)
	)


class GetEcmInfo:
	def pollEcmData(self):
		global data
		global old_ecm_time
		global info
		global ecm
		try:
			ecm_time = os.stat(ECM_INFO).st_mtime
		except:
			ecm_time = old_ecm_time
			data = EMPTY_ECM_INFO
			info = {}
			ecm = ''
		if ecm_time != old_ecm_time:
			oecmi1 = info.get('ecminterval1', '')
			oecmi0 = info.get('ecminterval0', '')
			info = {}
			info['ecminterval2'] = oecmi1
			info['ecminterval1'] = oecmi0
			old_ecm_time = ecm_time
			try:
				ecm = open(ECM_INFO, 'r').readlines()
			except:
				ecm = ''
			for line in ecm:
				d = line.split(':', 1)
				if len(d) > 1:
					info[d[0].strip()] = d[1].strip()
			if info and info.get("from") and config.softcam.hideServerName.value:
				info["from"] = "".join(["\u2022"] * len(info.get("from")))
			data = self.getText()
			return True
		else:
			info['ecminterval0'] = int(time.time() - ecm_time + 0.5)

	def getEcm(self):
		return (self.pollEcmData(), ecm)

	def getEcmData(self):
		self.pollEcmData()
		return data

	def getInfo(self, member, ifempty=''):
		self.pollEcmData()
		return str(info.get(member, ifempty))
	
	def getInfoRaw(self):
		self.pollEcmData()
		return info

	def getText(self):
		global ecm
		try:
			# info is dictionary
			using = info.get('using', '')
			if using:
				# CCcam
				if using == 'fta':
					self.textvalue = _("FTA")
				elif using == 'emu':
					self.textvalue = "EMU (%ss)" % (info.get('ecm time', '?'))
				else:
					hops = info.get('hops', None)
					if hops and hops != '0':
						hops = ' @' + hops
					else:
						hops = ''
					self.textvalue = info.get('address', '?') + hops + " (%ss)" % info.get('ecm time', '?')
			else:
				decode = info.get('decode', None)
				if decode:
					# gbox (untested)
					if info['decode'] == 'Network':
						cardid = 'id:' + info.get('prov', '')
						try:
							share = open('/tmp/share.info', 'r').readlines()
							for line in share:
								if cardid in line:
									self.textvalue = line.strip()
									break
							else:
								self.textvalue = cardid
						except:
							self.textvalue = decode
					else:
						self.textvalue = decode
					if ecm[1].startswith('SysID'):
						info['prov'] = ecm[1].strip()[6:]
					if info['response'] and 'CaID 0x' in ecm[0] and 'pid 0x' in ecm[0]:
						self.textvalue += " (0.%ss)" % info['response']
						info['caid'] = ecm[0][ecm[0].find('CaID 0x') + 7:ecm[0].find(',')]
						info['pid'] = ecm[0][ecm[0].find('pid 0x') + 6:ecm[0].find(' =')]
						info['provid'] = info.get('prov', '0')[:4]
				else:
					source = info.get('source', None)
					if source:
						# wicardd - type 2 / mgcamd
						caid = info.get('caid', None)
						if caid:
							info['caid'] = info['caid'][2:]
							info['pid'] = info['pid'][2:]
						info['provid'] = info['prov'][2:]
						time = ""
						for line in ecm:
							if 'msec' in line:
								line = line.split(' ')
								if line[0]:
									time = " (%ss)" % (float(line[0]) / 1000)
									continue
						self.textvalue = source + time
					else:
						reader = info.get('reader', '')
						if reader:
							hops = info.get('hops', None)
							if hops and hops != '0':
								hops = ' @' + hops
							else:
								hops = ''
							self.textvalue = reader + hops + " (%ss)" % info.get('ecm time', '?')
						else:
							response = info.get('response time', None)
							if response:
								# wicardd - type 1
								response = response.split(' ')
								self.textvalue = "%s (%ss)" % (response[4], float(response[0]) / 1000)
							else:
								self.textvalue = ""
			decCI = info.get('caid', info.get('CAID', '0'))
			provid = info.get('provid', info.get('prov', info.get('Provider', '0')))
			ecmpid = info.get('pid', info.get('ECM PID', '0'))
		except:
			ecm = ''
			self.textvalue = ""
			decCI = '0'
			provid = '0'
			ecmpid = '0'
		return self.textvalue, decCI, provid, ecmpid
