package io.github.tobehardoo.trippilot.userconfig;

import java.util.List;
import java.util.UUID;

import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 用户自建第三方 API 配置（设置页）：天气/高德/知识库/规划。 */
@RestController
@RequestMapping("/api/config/api-configs")
public class UserApiConfigController {

    private final UserApiConfigService service;

    public UserApiConfigController(UserApiConfigService service) {
        this.service = service;
    }

    @GetMapping
    List<UserApiConfig> list(@AuthenticationPrincipal Jwt jwt) {
        return service.list(userId(jwt));
    }

    @PutMapping
    void save(@AuthenticationPrincipal Jwt jwt, @RequestBody List<UserApiConfigService.SaveItem> items) {
        service.save(userId(jwt), items);
    }

    @DeleteMapping("/{provider}")
    void delete(@AuthenticationPrincipal Jwt jwt, @PathVariable String provider) {
        service.delete(userId(jwt), provider);
    }

    private UUID userId(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }
}