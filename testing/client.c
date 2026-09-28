/* SOURCE: Dr. Jhansi Prathuri, Merrimack College
*
* client_two_machine.c
* The CLIENT runs on Machine A.
* It connects to Machine B, sends a message, and receives a reply.
*/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#define PORT 8080
#define BUFFER_SIZE 256
int main(int argc, char *argv[])
{
int client_fd;
struct sockaddr_in server_addr;
char buffer[BUFFER_SIZE];
/* The server IP address is provided on the command line. */
if (argc != 2)
{
printf("Usage: %s SERVER_IP\n", argv[0]);
printf("Example: %s 192.168.1.105\n", argv[0]);
return 1;
}
/* Create a TCP socket. */
client_fd = socket(AF_INET, SOCK_STREAM, 0);
if (client_fd == -1)
{
perror("socket");
return 1;
}
/* Configure the server address. */
server_addr.sin_family = AF_INET;
server_addr.sin_port = htons(PORT);
/* Convert the server IP address from text to binary form. */
if (inet_pton(AF_INET, argv[1], &server_addr.sin_addr) <= 0)
{
perror("inet_pton");
close(client_fd);
return 1;
}
/* Connect to Machine B. */
if (connect(client_fd,
(struct sockaddr *)&server_addr,
sizeof(server_addr)) == -1)
{
perror("connect");
close(client_fd);
return 1;
}
printf("Student Client - PID: %d\n", getpid());
printf("Connected to server %s:%d\n", argv[1], PORT);
/* Send a message to the server process. */
char message[] = "Student requests course schedule.";
write(client_fd, message, strlen(message) + 1);
printf("Message sent.\n");
/* Receive the server's response. */
int n = read(client_fd, buffer, BUFFER_SIZE - 1);
if (n > 0)
{
buffer[n] = '\0';
printf("Server response: %s\n", buffer);
}
close(client_fd);
return 0;
}
