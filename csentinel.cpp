#include <linux/ioctl.h>
#include <sys/time.h>
#include <linux/videodev2.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/poll.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/types.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

struct buf_t {
	void *map;
	size_t len;
} *bufs;

unsigned int nbufs;
unsigned int trigger_gap;
unsigned char *mask = NULL;

unsigned char* motArray[64];
unsigned int motHead = 0;
unsigned int motTail = 0;

int count = 0;
int pgmCount = 0;
bool running = true;

unsigned short int* pgmArray;

void mask_init( int threshold )
{
  char path[256];
  char buff[20];

  int c;
  bool complete = false;

  mask     = (unsigned char*)malloc( 307200 );
  pgmArray = (unsigned short int*)malloc( 307200*2 );

  strcpy( path, getenv( "HOME" ) );
  strcat( path, "/mask.pgm" );
  FILE* file = fopen( path, "r" );
  
  for (;;)
    {
      if ( file == 0 )
        break;

      if ( fgetc( file ) != 'P' )
        break;
      if ( fgetc( file ) != '5' )
        break;
      if ( fgetc( file ) != '\n' )
        break;

      // Check for comment line
      if ( (c = fgetc( file )) != '6' )
        {
          if ( c == '#' )
            {
              while ( fgetc( file ) != '\n' ) ;
              if ( (c = fgetc( file )) != '6' )
                break;
            }
          else
            break;
        }
      
      fread( buff, 11, 1, file );
      if ( strncmp( buff, "40 480\n255\n", 11 ) != 0 )
        break;

      fread( mask, 307200, 1, file );
      fclose( file );

      for ( int i = 0; i < 307200; ++i )
        {
          if ( mask[i] == 0 || mask[i] == 255 )
            mask[i] = 255;
          else
            mask[i] = threshold;
        }

      complete = true;
      break;
    }

  if ( ! complete )
    {
      printf( "No mask, flat mask generated.\n" );
      memset( mask, threshold, 307200 );
    }
}

int camera_init()
{
  struct v4l2_capability cap;
  struct v4l2_input input;
  struct v4l2_standard standard;
  struct v4l2_format fmt;
  struct v4l2_requestbuffers req;
  v4l2_std_id std_id;
 
  unsigned int n = 1;
 
  int fd = open( "/dev/video0", O_RDWR );
  if ( fd < 0 )
    goto err0;

  if ( ioctl(fd, VIDIOC_QUERYCAP, &cap ) < 0 )
    goto err1;

  if ( !(cap.capabilities & V4L2_CAP_VIDEO_CAPTURE) ) 
    {
      fprintf(stderr, "Cannot capture video.\n");
      exit(0);
    }

  if ( !(cap.capabilities & V4L2_CAP_STREAMING) ) 
    {
      fprintf(stderr, "Does not support mmap mode.\n");
      exit(0);
    }

  if ( ioctl(fd, VIDIOC_S_INPUT, &n) < 0 )
    goto err1;

  memset( &input, 0, sizeof(input) );

  if ( ioctl(fd, VIDIOC_G_INPUT, &input.index) < 0 )
    goto err1;

  if ( ioctl(fd, VIDIOC_ENUMINPUT, &input) < 0 )
    goto err1;

  // Check for NTSC support.
  if ( !(input.std & V4L2_STD_NTSC_M) )
    abort();

  std_id = V4L2_STD_NTSC_M;
  if ( ioctl(fd, VIDIOC_S_STD, &std_id) < 0 )
    goto err1;

  n = 0;
  do {
    memset(&standard, 0, sizeof(standard));
    standard.index = n++;

    if ( ioctl(fd, VIDIOC_ENUMSTD, &standard) < 0 )
      break;

//  fprintf(stdout, " supports : %s\n", standard.name);
  } while (1);

  memset(&fmt, 0, sizeof(fmt));
  fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  fmt.fmt.pix.width = 640;
  fmt.fmt.pix.height = 480;
  fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_YUV422P; /* Planar YUV */
  fmt.fmt.pix.field = V4L2_FIELD_INTERLACED;

  if ( ioctl(fd, VIDIOC_S_FMT, &fmt) < 0 )
    goto err1;

  memset( &req, 0, sizeof(req) );
  req.count = 20;
  req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  req.memory = V4L2_MEMORY_MMAP;

  if ( ioctl(fd, VIDIOC_REQBUFS, &req) < 0 )
    goto err1;

  // Check for sufficient buffer memory.
  if (req.count < 8)
    abort();

  bufs = (buf_t*)calloc(req.count, sizeof(*bufs));
  nbufs = req.count;

  if ( bufs == NULL )
    abort();

  for (nbufs = 0; nbufs < req.count; nbufs++) 
    {
      struct v4l2_buffer buf;
      memset(&buf, 0, sizeof(buf));

      buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      buf.memory = V4L2_MEMORY_MMAP;
      buf.index = nbufs;

      if ( ioctl(fd, VIDIOC_QUERYBUF, &buf) < 0 )
        goto err1;

      bufs[nbufs].len = buf.length;
      bufs[nbufs].map = mmap(NULL, buf.length, PROT_READ | PROT_WRITE, MAP_SHARED, 
                             fd, buf.m.offset);

      if (bufs[nbufs].map == MAP_FAILED)
        abort();
    }

  for (n = 0; n < nbufs; n++) 
    {
      struct v4l2_buffer buf;

      memset(&buf, 0, sizeof(buf));

      buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      buf.memory = V4L2_MEMORY_MMAP;
      buf.index = n;

      if ( ioctl(fd, VIDIOC_QBUF, &buf) < 0 )
        return -1;
    }

  enum v4l2_buf_type type;
  type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  if ( ioctl(fd, VIDIOC_STREAMON, &type) < 0 )
    return -1;

  return fd;

err1: close(fd);
err0: perror("/dev/video0");
	
  return -1;
}
	
void camera_exit(int fd)
{
	unsigned int n;

	enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
	ioctl(fd, VIDIOC_STREAMOFF, &type);

	for (n = 0; n < nbufs; n++)
		munmap(bufs[n].map, bufs[n].len);

	free(bufs);
	close(fd);
}

void copy_image(void *map, unsigned long ts, unsigned long tus)
{
  unsigned int sentinel_sum;
  int diff;
  char cmd[256];
  char path[256];
  char name[256];
  char nextPath[256];
  struct stat info;

  static char history[256];
  static FILE* jpegFile = 0;
  static FILE* pgmFile = 0;
  static int second_total = 0;

  if ( pgmCount == 0 )
    {
      sprintf( name, "s%08lx_%03ld", ts, tus / 1000 );

      strcpy( path, getenv( "HOME" ) );
      strcat( path, "/exposures" );
      if ( stat( path, &info ) < 0 )
        mkdir( path, 0777 );

      sprintf( nextPath, "/s%04lx", ts >> 16 );
      strcat( path, nextPath );
      if ( stat( path, &info ) < 0 )
        mkdir( path, 0777 );

      sprintf( nextPath, "/s%06lx", ts >> 8 );
      strcat( path, nextPath );
      if ( stat( path, &info ) < 0 )
        mkdir( path, 0777 );

      sprintf( nextPath, "/%s.pgm", name );
      strcat( path, nextPath );

      memset( pgmArray, 0, 307200*2 );
      pgmFile = fopen( path, "w" );
    }

  if ( count == 0 ) 
    {
      sprintf( name, "s%08lx_%03ld", ts, tus / 1000 );

      strcpy( path, getenv( "HOME" ) );
      strcat( path, "/images" );
      if ( stat( path, &info ) < 0 )
        mkdir( path, 0777 );

      sprintf( nextPath, "/s%04lx", ts >> 16 );
      strcat( path, nextPath );
      if ( stat( path, &info ) < 0 )
        mkdir( path, 0777 );

      sprintf( nextPath, "/s%06lx", ts >> 8 );
      strcat( path, nextPath );
      if ( stat( path, &info ) < 0 )
        mkdir( path, 0777 );

      sprintf( nextPath, "/%s.jpg", name );
      strcat( path, nextPath );

      sprintf( cmd, "cjpeg -grayscale -quality 80 -dct float -outfile %s", path );
      jpegFile = popen( cmd, "w" );
      if ( jpegFile != 0 )
        fprintf( jpegFile, "P5 640 14400 255\n" );

      fprintf( stdout, "%s ", name );
      strcpy( history, "" );
      second_total = 0;
    }

  unsigned char* buf = (unsigned char*)malloc( 307200 );
  if ( buf == NULL )
    abort();
  
  memcpy( buf, map, 307200 );
  motArray[ motTail ] = buf;
  motTail = (motTail + 1 ) % 32;

  sentinel_sum = 0;

  unsigned int gap = (motTail-motHead) % 32;

  if ( gap > trigger_gap)
    {
      unsigned char* cmp = motArray[ motHead ];
      motArray[ motHead ] = 0;
      motHead = (motHead + 1) % 32;
 
      // This is the time critical section? 
      for ( int n = 0; n < 307200; n++ ) 
        {
          diff = (int)buf[n] - (int)cmp[n];
		
          if ( diff > (int)mask[n] )
            sentinel_sum++;

          pgmArray[n] += buf[n];
        }

      free(cmp);
    }

  count = (count+1) % 30;
  pgmCount = (pgmCount+1) % 256;

  if ( jpegFile != 0 ) 
    {
      fwrite( buf, 307200, 1, jpegFile );
      if ( count == 0 )
        pclose( jpegFile );
    }

  if ( pgmFile != 0 && pgmCount == 0 )
    {
      fprintf( pgmFile, "P5 640 480 255\n" );
      for ( int i = 0; i < 307200; ++i )
        {
          unsigned char c;

          c = pgmArray[i] >> 8;

          fwrite( &c, 1, 1, pgmFile );
        }
      fclose( pgmFile );
      pgmFile = 0;
    }

  second_total += sentinel_sum;
  if ( sentinel_sum == 0 )
    strcat( history, "0 " );
  else
    {
      sprintf( name, "%x ", sentinel_sum );
      strcat( history, name );
    }

  if ( count == 0 )
    {
      if ( second_total == 0 )
        fputs( "Z", stdout );
      else
        fputs( history, stdout );

      fputs( "\n", stdout );
      fflush( stdout );
    }
}

void record_exit(int sig)
{
  running = false;
  // fputs( "Shutting down\n", stderr );
}

int main( int argc, char* argv[] )
{
  struct v4l2_buffer buf;
  struct pollfd pollfd;

  signal(SIGTERM, record_exit);

  int threshold = 50;

  if ( argc >= 2 )
    threshold = atoi( argv[1] );

  mask_init( threshold );

  trigger_gap = 10;

  if ( argc >= 3 )
    trigger_gap = atoi( argv[2] );

  int fd = camera_init();
  if ( fd < 0 )
    abort();

  pollfd.fd = fd;
  pollfd.events = POLLIN;
  pollfd.revents = 0;

  memset( &buf, 0, sizeof(buf) );

  buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
  buf.memory = V4L2_MEMORY_MMAP;

  while ( running || count != 0 )
    {
      int res = poll( &pollfd, 1, 1000 );

      // If we were interrupted by a signal, treat it as the idle case.
      if (res == 0 || ((res < 0) && (errno == EINTR)))
        continue;
		
      if (res < 0)
        abort();
					
      // read frame
      res = ioctl( fd, VIDIOC_DQBUF, &buf );
		
      if ( res < 0 && errno == EAGAIN )
        continue;
		
      if ( res < 0 )
        abort();

      copy_image( bufs[buf.index].map, buf.timestamp.tv_sec, buf.timestamp.tv_usec );
		
      if ( ioctl(fd, VIDIOC_QBUF, &buf) < 0 )
        abort();
    }

  camera_exit(fd);

  return 0;
}


