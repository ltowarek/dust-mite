// http://<IP>/?command=2

#include <WiFi.h>
#include <WebServer.h>

#define WIFI_SSID "<SSID>"
#define WIFI_PASSWORD "<PASSWORD>"

#define COMMAND_START '1'
#define COMMAND_END '2'

#define LED_PIN 2

WebServer server(80);

char command = 0;

void handleRoot() {
  String message;
  
  String raw_command = server.arg("command");
  if (raw_command != "") {
    command = raw_command[0];
    message = "Command: ";
    message += command;
  } else {
    message = "Command not found";
    command = 0;
  }

  server.send(200, "text/plain", message);
}

void setup()
{ 
  pinMode(LED_PIN, OUTPUT);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }

  server.on("/", handleRoot);
  server.begin();
}

void loop()
{
  server.handleClient();

  if (command == COMMAND_START) {
    digitalWrite(LED_PIN, HIGH);
  } else if (command == COMMAND_END) {
    digitalWrite(LED_PIN, LOW);
  }

  delay(2);
}
