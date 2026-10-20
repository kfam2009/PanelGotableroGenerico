import unittest
import xml.etree.ElementTree as ET
from vmix_control import SOURCE,VmixAPI,VmixGraphicControl

class FakeVmix:
    def __init__(self,with_graphic=False):
        self.inputs=[{'key':'cam','number':'1','title':'Camara'}];self.overlay='';self.calls=[]
        if with_graphic:self.inputs.append({'key':'g1','number':'2','title':SOURCE})
    def state(self):
        root=ET.Element('vmix');inputs=ET.SubElement(root,'inputs')
        for item in self.inputs:ET.SubElement(inputs,'input',item)
        overlays=ET.SubElement(root,'overlays');first=ET.SubElement(overlays,'overlay',number='1');first.text=self.overlay or None
        ET.SubElement(overlays,'overlay',number='2')
        return root
    def call(self,function,**params):
        self.calls.append((function,params))
        if function=='AddInput':self.inputs.append({'key':'new','number':str(len(self.inputs)+1),'title':params['Value']})
        elif function=='SetInputName':next(i for i in self.inputs if i['key']==params['Input'])['title']=params['Value']
        elif function=='OverlayInput1In':self.overlay=next(i for i in self.inputs if i['key']==params['Input'])['number']
        elif function=='OverlayInput1Out':self.overlay=''

class VmixTests(unittest.TestCase):
    def control(self,fake):
        control=VmixGraphicControl(api=fake);control.sleep=lambda *_:None;return control
    def test_status_only_reads(self):
        fake=FakeVmix(True);status=self.control(fake).status()
        self.assertEqual((status['ready'],status['enabled'],status['switcher']),(True,False,'vMix'))
        self.assertEqual(fake.calls,[])
    def test_install_adds_one_hidden_browser_input(self):
        fake=FakeVmix();result=self.control(fake).install('http://172.27.4.221:8772/graphics.html')
        self.assertTrue(result['created']);self.assertFalse(result['enabled'])
        self.assertEqual(fake.calls[0],('AddInput',{'Value':'Browser|http://172.27.4.221:8772/graphics.html'}))
        self.assertEqual(fake.calls[1],('SetInputName',{'Input':'new','Value':SOURCE}))
        self.assertEqual(fake.overlay,'')
        calls=len(fake.calls);self.control(fake).install('http://x/graphics.html');self.assertEqual(len(fake.calls),calls)
    def test_show_takes_over_and_hide_only_removes_the_graphic(self):
        fake=FakeVmix(True);control=self.control(fake)
        self.assertTrue(control.set_enabled(True,'http://172.27.4.221:8772/graphics.html')['enabled'])
        self.assertEqual(fake.calls[0],('BrowserNavigate',{'Input':'g1','Value':'http://172.27.4.221:8772/graphics.html'}))
        self.assertEqual(fake.calls[1],('OverlayInput1In',{'Input':'g1'}))
        self.assertFalse(control.set_enabled(False)['enabled'])
        fake.overlay='1';fake.calls.clear()
        self.assertFalse(control.set_enabled(False)['enabled']);self.assertEqual(fake.calls,[])
        with self.assertRaises(ValueError):control.set_enabled('true')
    def test_only_graphic_functions_are_allowed(self):
        api=VmixAPI.__new__(VmixAPI)
        for function in ('StartStreaming','Cut','Fade','OverlayInput1Off','RemoveInput','OverlayInputXIn'):
            with self.assertRaises(ValueError):api.call(function)

if __name__=='__main__':unittest.main()
