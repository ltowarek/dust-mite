// http://<IP>/?command=3&value=127

#include <WiFi.h>
#include <WebServer.h>

#define WIFI_SSID "<SSID>"
#define WIFI_PASSWORD "<PASSWORD>"

#define COMMAND_START '1'
#define COMMAND_END '2'
#define COMMAND_TURN '3'
#define COMMAND_BRAKE '4'
#define COMMAND_ACCELERATE '5'

#define LED_PIN 2

WebServer server(80);

char command = 0;
int value = 0;

void handleRoot() {
  String message;
  
  String raw_command = server.arg("command");
  if (raw_command != "") {
    command = raw_command[0];
    message = "Command: ";
    message += command;

    String raw_value = server.arg("value");
    if (raw_value != "") {
      if (command==COMMAND_TURN) {
        value = raw_value.toInt();
      } else if (command==COMMAND_BRAKE) {
        value = raw_value.toInt();
      } else if (command==COMMAND_ACCELERATE) {
        value = raw_value.toInt();
      } else {
        message = "Value not found";
        command = 0;
      }
    }
  } else {
    message = "Command not found";
    command = 0;
  }

  server.send(200, "text/plain", message);
}

void setup()
{ 
  Serial.begin(115200);

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

  if (command != 0) {
    switch (command) {
      case COMMAND_START:
        Serial.println("COMMAND_START");
        digitalWrite(LED_PIN, HIGH);
        break;
      case COMMAND_END:
        Serial.println("COMMAND_END");
        digitalWrite(LED_PIN, LOW);
        break;
      case COMMAND_TURN:
        Serial.printf("COMMAND_TURN: %d\n", value);
        break;
      case COMMAND_BRAKE:
        Serial.printf("COMMAND_BRAKE: %d\n", value);
        break;
      case COMMAND_ACCELERATE:
        Serial.printf("COMMAND_ACCELERATE: %d\n", value);
        break;
      default:
        Serial.println("Unknown command");
    }
    command = 0;
    value = 0;
  }

  delay(2);
}
