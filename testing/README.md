# Testing Suite

The purpose of this folder is to hold any test code developed over the course of the project.

# Tests and Instructions

1. The Raspberry Pi can receive and respond to messaged
    - Download server.c onto either the Raspberry Pi or a machine of your choice (ensure said machine has gcc installed) 
      and then client.c onto the other machine.

    - compile and run the server code (gcc <server.c> -o <name-of-compiled-code>, then ./<name-of-compiled-code>)
      Ex: gcc server.c -o server, then ./server

      You should see something like:
      "Campus Server - PID: 1834
      Waiting for a client on port 8080..."

    - compile and run the client code appening the IP address of the machine you're runnning the server code on (./client <IP-address>).
      Ex: ./client 0.0.0.0

      You should see something like:
      "Student Client -=PID: 46102
       Connected to server <0.0.0.0:8000
       Message sent.
       Server response: . . .>"

       And then on the server side you should now see:
       "Campus Server - PID: 1834
        Waiting for a client on port 8080...
        Client connected.
        Received: Student requests course schedule.
        Response sent."