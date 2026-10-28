package com.rag.gateway.auth;

import java.time.Instant;

import com.rag.gateway.security.GatewaySecurityProperties;
import com.rag.gateway.user.RegisterRequest;
import com.rag.gateway.user.UserEntity;
import com.rag.gateway.user.UserResponse;
import com.rag.gateway.user.UserService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final JwtEncoder jwtEncoder;
    private final GatewaySecurityProperties properties;
    private final UserService userService;

    public AuthController(JwtEncoder jwtEncoder, GatewaySecurityProperties properties, UserService userService) {
        this.jwtEncoder = jwtEncoder;
        this.properties = properties;
        this.userService = userService;
    }

    @PostMapping("/register")
    public UserResponse register(@Valid @RequestBody RegisterRequest request) {
        UserEntity user = userService.register(request);
        return new UserResponse(
                user.getId(),
                user.getUsername(),
                user.getEmail(),
                user.getCreatedAt().toString()
        );
    }

    @PostMapping("/token")
    public TokenResponse token(@Valid @RequestBody TokenRequest request) {
        UserEntity user;
        try {
            user = userService.authenticate(request.username(), request.password());
        } catch (ResponseStatusException exc) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid credentials");
        }

        Instant now = Instant.now();
        Instant expiresAt = now.plus(properties.tokenTtl());
        JwtClaimsSet claims = JwtClaimsSet.builder()
                .issuer(properties.issuer())
                .issuedAt(now)
                .expiresAt(expiresAt)
                .subject(user.getUsername())
                .claim("scope", "chat")
                .build();
        JwsHeader header = JwsHeader.with(MacAlgorithm.HS256).build();
        String token = jwtEncoder.encode(JwtEncoderParameters.from(header, claims)).getTokenValue();

        return new TokenResponse(token, "Bearer", expiresAt);
    }
}
