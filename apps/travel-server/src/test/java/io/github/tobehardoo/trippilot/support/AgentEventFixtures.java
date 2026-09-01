package io.github.tobehardoo.trippilot.support;

import java.nio.file.Files;
import java.nio.file.Path;

/** Loads the cross-language fixtures under {@code contracts/fixtures/}. */
public final class AgentEventFixtures {

    private AgentEventFixtures() {
    }

    public static String load(String directory, String fixtureName) {
        Path relative = Path.of("contracts", "fixtures", directory, fixtureName);
        Path workingDirectory = Path.of("").toAbsolutePath();
        Path fixture = workingDirectory.resolve(relative);
        if (!Files.isRegularFile(fixture)) {
            fixture = workingDirectory.resolve(Path.of("..", ".."))
                    .resolve(relative)
                    .normalize();
        }
        try {
            return Files.readString(fixture);
        } catch (java.io.IOException exception) {
            throw new IllegalStateException("cannot read fixture " + relative, exception);
        }
    }
}
