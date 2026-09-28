/* SOURCE: Dr. Jhansi Prathuri, Merrimack College
*
* server_two_machine.c
* The SERVER runs on Machine B.
* It waits for a client, receives a message, and sends a reply.
*/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>
#define PORT 8080
#define BUFFER_SIZE 256
int main(void)
{
int server_fd, client_fd;
struct sockaddr_in server_addr;
char buffer[BUFFER_SIZE];
/* Create a TCP socket. */
server_fd = socket(AF_INET, SOCK_STREAM, 0);
if (server_fd == -1)
{
perror("socket");
return 1;
}
/* Configure the server address. */
server_addr.sin_family = AF_INET;
server_addr.sin_addr.s_addr = INADDR_ANY;
server_addr.sin_port = htons(PORT);
/* Bind the socket to port 8080. */
if (bind(server_fd,
(struct sockaddr *)&server_addr,
sizeof(server_addr)) == -1) {
perror("bind");
close(server_fd);
return 1;
}
/* Listen for incoming client connections. */
if (listen(server_fd, 5) == -1)
{
perror("listen");
close(server_fd);
return 1;
}
printf("Campus Server - PID: %d\n", getpid());
printf("Waiting for a client on port %d...\n", PORT);
/* Wait until a client connects. */
client_fd = accept(server_fd, NULL, NULL);
if (client_fd == -1)
{
perror("accept");
close(server_fd);
return 1;
}
printf("Client connected.\n");
/* Receive a message from the client. */
int n = read(client_fd, buffer, BUFFER_SIZE - 1);
if (n > 0)
{
buffer[n] = '\0';
printf("Received: %s\n", buffer);
}
/* Send a response back to the client. */
char reply[] = "Your request was received by the campus server.";
write(client_fd, reply, strlen(reply) + 1);
printf("Response sent.\n");
close(client_fd);
close(server_fd);
return 0;
}
