package io.github.tobehardoo.trippilot.security;

import java.io.IOException;

import org.junit.jupiter.api.Test;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.MutablePropertySources;
import org.springframework.core.env.PropertySourcesPropertyResolver;
import org.springframework.core.io.ClassPathResource;

import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ApplicationSecurityConfigurationTest {

    @Test
    void requiresJwtSecretFromTheEnvironment() throws IOException {
        var source = new YamlPropertySourceLoader()
                .load("application", new ClassPathResource("application.yml"))
                .getFirst();
        var sources = new MutablePropertySources();
        sources.addLast(source);
        var resolver = new PropertySourcesPropertyResolver(sources);

        assertThatThrownBy(() -> resolver.getRequiredProperty("app.security.jwt-secret"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("JWT_SECRET");
    }
}
