# -*- coding: utf-8 -*-
from Components.Converter.Converter import Converter
from Components.Element import cached


class ProgressToText(Converter):
	def __init__(self, type):
		Converter.__init__(self, type)
		self.in_percent = "InPercent" in type.split(',')

	@cached
	def getText(self):
		r = self.source.range
		v = self.source.value

		if self.in_percent:
			if r:
				return "%d %%" % (v * 100 / r)
			else:
				return None
		else:
			return "%d / %d" % (v, r)

	text = property(getText)
