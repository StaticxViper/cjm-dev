import subprocess
import sys
#sys.path.append('/home/pi/1.Repos/sxv-projects')

#from Managers.LogManager.log_manager import LogManager
#from Managers.NotificationManager.notification_manager import MyClient

class UpdateManager():
    """ Update the Raspberry Pi and other tools """

    def __init__(self):
        """ Initialize the UpdateManager """
        #self.log = LogManager()
        #self.notif = MyClient()

        self.update_log = '/home/pi/1.Repos/sxv-projects/docs/logs/update_log.txt'

    def update_raspberry_pi(self):
        """ Update the Raspberry Pi """
        try:
            subprocess.run(['sudo', 'apt-get', 'update'], check=True)
            subprocess.run(['sudo', 'apt-get', 'upgrade', '-y'], check=True)
            self.log.write_to_file(self, self.update_log, "Raspberry Pi updated successfully")
            self.notif.user_message = 'Update successful!'
            self.notif.run(self.notif.TOKEN)
        except subprocess.CalledProcessError as cpe:
            self.log.write_to_file(self, self.update_log, f"Failed to update Raspberry Pi due to error: {cpe}")
            error_message = f'Failed to update Raspberry Pi due to an error... {cpe}'
            self.notif.user_message = error_message
            self.notif.run(self.notif.TOKEN)

    def update(self, command, location):
        """ Send a command to update another tool, software, etc. """
        try:
            subprocess.run(command, shell=True, check=True)
            if location:
                self.log.write_to_file(self, location, "Update successful!")
            else:
                self.log.write_to_file(self, self.update_log, "Update successful!")
            self.notif.user_message = 'Update successful!'
            self.notif.run(self.notif.TOKEN)
        except subprocess.CalledProcessError as cpe:
            self.log.write_to_file(self, self.update_log, f"Failed to update due to error: {cpe}")
            error_message = 'Failed to update...'
            self.notif.user_message = error_message
            self.notif.run(self.notif.TOKEN)

if __name__ == "__main__":
    test_instance = UpdateManager()
    test_instance.update_raspberry_pi()