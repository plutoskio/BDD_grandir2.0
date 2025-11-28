import xml.etree.ElementTree as ET

ns = {'kml': 'http://www.opengis.net/kml/2.2'}

try:
    tree = ET.parse('creche.kml')
    root = tree.getroot()
    
    placemarks = root.findall('.//kml:Placemark', ns)
    print(f"Found {len(placemarks)} placemarks.")
    
    for p in placemarks[:3]:
        name = p.find('kml:name', ns).text
        print(f"Name: {name}")
        
        # Try to find Zip in ExtendedData
        zip_code = None
        for data in p.findall('.//kml:Data', ns):
            if data.get('name') == 'CODE POSTAL':
                zip_code = data.find('kml:value', ns).text
                break
        print(f"Zip: {zip_code}")
        
except Exception as e:
    print(f"Error: {e}")
