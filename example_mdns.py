import sys
print (sys.executable)
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf


class MyListener(ServiceListener):

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        print(f"Service {name} updated")

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        print(f"Service {name} removed")

    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        print(f"Service {name} added, service info: {info}")

list_services = [


    # "_http._tcp.local.", #some WIFI throttles have an http web interface for configuration
    #                      but they are not the HUB and should be excluded
    #"_hap._tcp.local.",

    "_openlcb-can._tcp.local."
]

zeroconf = Zeroconf()

listener = MyListener()
#browser = ServiceBrowser(zeroconf, "_openlcb-can._tcp.local.", listener)
browser = ServiceBrowser(zeroconf, list_services, listener)

try:
    input("Press enter to exit...\n\n")
finally:
    zeroconf.close()