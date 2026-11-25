package app.lodestar.mobile;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

/** The update offer: only a strictly newer build the computer states plainly; never a downgrade or a guess. */
public class UpdaterTest {
    @Test
    public void readsTheComputersBuild() {
        String json = "{\"code\": 1234, \"name\": \"2026.11.23-0412\", \"size\": 63488}";
        assertEquals(1234, Updater.parseCode(json));
        assertEquals("2026.11.23-0412", Updater.parseName(json));
    }

    @Test
    public void anythingElseIsNoUpdate() {
        for (String bad : new String[] {null, "", "{}", "{\"error\": \"no Android app\"}", "{\"code\": \"x\"}", "<html>"}) {
            assertEquals(bad, -1, Updater.parseCode(bad));
        }
        assertEquals("", Updater.parseName("{\"name\": \"<b\\\"x\"}"));
    }

    @Test
    public void onlyStrictlyNewerIsOffered() {
        assertTrue(Updater.isNewer(5, 4));
        assertFalse(Updater.isNewer(4, 4));
        assertFalse(Updater.isNewer(3, 4));  // never a downgrade
        assertFalse(Updater.isNewer(-1, 0));
        assertFalse(Updater.isNewer(9, Long.MAX_VALUE));  // installed version unknown: never offered
    }
}
