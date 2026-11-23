package app.lodestar.mobile;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** The app only ever loads your own network: private IPv4 or .local, nothing else. */
public class AddressTest {
    @Test
    public void privateAddressesAreAllowed() {
        for (String h : new String[] {"192.168.1.153", "10.0.0.2", "172.16.0.1", "172.31.255.254", "192.168.42.129", "lodestar.local",
                "100.64.0.1", "100.101.102.103", "100.127.255.254"}) {
            assertTrue(h, MainActivity.isPrivate(h));
        }
    }

    @Test
    public void everythingElseIsRefused() {
        for (String h : new String[] {"8.8.8.8", "172.32.0.1", "172.15.0.1", "192.169.1.1", "example.com", "127.0.0.1",
                "192.168.1", "192.168.1.256", "1.2.3.4.5", "", "localhost", "evil.local.example.com",
                "100.63.255.255", "100.128.0.1"}) {
            assertFalse(h, MainActivity.isPrivate(h));
        }
        assertFalse(MainActivity.isPrivate(null));
    }

    @Test
    public void findNeverScansACarrierOrVpnRange() {
        assertTrue(MainActivity.scannable("192.168.1.20"));
        assertTrue(MainActivity.scannable("10.0.0.2"));
        assertFalse(MainActivity.scannable("100.70.1.2")); // mobile data's shared NAT: other subscribers
        assertFalse(MainActivity.scannable("8.8.8.8"));
    }
}
