use pyo3::prelude::*;

use socket2::{Domain, Protocol, Socket, Type};
use std::{
    net::{IpAddr, SocketAddr},
    time::Duration,
};

#[derive(Debug)]
pub struct SocketHeld {
    pub socket: Socket,
}

impl SocketHeld {
    pub fn new(ip: String, port: u16) -> PyResult<SocketHeld> {
        let ip: IpAddr = ip.parse()?;
        let socket = if ip.is_ipv4() {
            Socket::new(Domain::IPV4, Type::STREAM, Some(Protocol::TCP))?
        } else {
            Socket::new(Domain::IPV6, Type::STREAM, Some(Protocol::TCP))?
        };

        let address = SocketAddr::new(ip, port);

        #[cfg(not(target_os = "windows"))]
        socket.set_reuse_port(true)?;

        // TCP tuning
        socket.set_tcp_nodelay(true)?; // Disable Nagle
        socket.set_reuse_address(true)?;

        // set keepalive with 60s interval
        let keepalive = socket2::TcpKeepalive::new().with_time(Duration::from_secs(60));
        socket.set_keepalive(true)?;
        socket.set_tcp_keepalive(&keepalive)?;
        socket.set_linger(Some(Duration::from_secs(0)))?; // Fast close

        // Set Increase buffer sizes
        socket.set_recv_buffer_size(256 * 1024)?; // 256KB
        socket.set_send_buffer_size(256 * 1024)?; // 256KB

        // Linux-specific optimizations
        #[cfg(target_os = "linux")]
        {
            use std::os::unix::io::AsRawFd;
            let fd = socket.as_raw_fd();

            // Enable TCP_FASTOPEN
            unsafe {
                let enable: libc::c_int = 5; // Queue length
                libc::setsockopt(
                    fd,
                    libc::IPPROTO_TCP,
                    libc::TCP_FASTOPEN,
                    &enable as *const _ as *const libc::c_void,
                    std::mem::size_of::<libc::c_int>() as libc::socklen_t,
                );

                // Enable TCP_QUICKACK
                let enable: libc::c_int = 1;
                libc::setsockopt(
                    fd,
                    libc::IPPROTO_TCP,
                    libc::TCP_QUICKACK,
                    &enable as *const _ as *const libc::c_void,
                    std::mem::size_of::<libc::c_int>() as libc::socklen_t,
                );
            }
        }

        socket.set_nonblocking(true)?;
        socket.bind(&address.into())?;

        socket.listen(8192)?;

        Ok(SocketHeld { socket })
    }

    pub fn try_clone(&self) -> PyResult<SocketHeld> {
        let copied = self.socket.try_clone()?;
        Ok(SocketHeld { socket: copied })
    }

    pub fn get_socket(&self) -> Socket {
        self.socket.try_clone().unwrap()
    }
}
