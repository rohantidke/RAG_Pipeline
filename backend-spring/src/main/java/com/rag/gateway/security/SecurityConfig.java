package com.rag.gateway.security;

import java.nio.charset.StandardCharsets;
import java.util.List;

import javax.crypto.spec.SecretKeySpec;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import com.nimbusds.jose.proc.SecurityContext;
import com.rag.gateway.ratelimit.RateLimitFilter;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.util.matcher.AntPathRequestMatcher;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http, RateLimitFilter rateLimitFilter) throws Exception {
        http
                .csrf(csrf -> csrf.disable()) // Disable CSRF for stateless APIs
                .cors(Customizer.withDefaults()) // Enable CORS  
                .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS)) // No session management
                .authorizeHttpRequests(authorize -> authorize // Allow unauthenticated access to the token endpoint and health/info endpoints
                .requestMatchers(new AntPathRequestMatcher("/api/auth/token", HttpMethod.POST.name())).permitAll()
                .requestMatchers(new AntPathRequestMatcher("/api/auth/register", HttpMethod.POST.name())).permitAll()
                .requestMatchers(new AntPathRequestMatcher("/actuator/health")).permitAll()
                .requestMatchers(new AntPathRequestMatcher("/actuator/info")).permitAll()
                .requestMatchers(new AntPathRequestMatcher("/error")).permitAll()
                .requestMatchers(new AntPathRequestMatcher("/api/**")).authenticated()
                .anyRequest().denyAll()
                )
                .exceptionHandling(exceptions -> exceptions
                .authenticationEntryPoint((request, response, exception)
                        -> writeError(response, HttpServletResponse.SC_UNAUTHORIZED, "Missing or invalid bearer token"))
                .accessDeniedHandler((request, response, exception)
                        -> writeError(response, HttpServletResponse.SC_FORBIDDEN, "Access denied"))
                )
                .oauth2ResourceServer(oauth2 -> oauth2.jwt(Customizer.withDefaults()))
                .addFilterAfter(rateLimitFilter, BearerTokenAuthenticationFilter.class);

        return http.build();
    }

    @Bean
    JwtEncoder jwtEncoder(GatewaySecurityProperties properties) {
        return new NimbusJwtEncoder(new ImmutableSecret<SecurityContext>(properties.jwtSecret().getBytes(StandardCharsets.UTF_8)));
    }

    @Bean
    JwtDecoder jwtDecoder(GatewaySecurityProperties properties) {
        SecretKeySpec secretKey = new SecretKeySpec(properties.jwtSecret().getBytes(StandardCharsets.UTF_8), "HmacSHA256");
        return NimbusJwtDecoder
                .withSecretKey(secretKey)
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
    }

    @Bean
    PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    CorsConfigurationSource corsConfigurationSource(GatewaySecurityProperties properties) {
        CorsConfiguration configuration = new CorsConfiguration();
        configuration.setAllowedOrigins(properties.corsAllowedOrigins());
        configuration.setAllowedMethods(List.of("GET", "POST", "DELETE", "OPTIONS"));
        configuration.setAllowedHeaders(List.of(HttpHeaders.AUTHORIZATION, HttpHeaders.CONTENT_TYPE, HttpHeaders.ACCEPT));
        configuration.setExposedHeaders(List.of(HttpHeaders.WWW_AUTHENTICATE, "X-RateLimit-Limit", "X-RateLimit-Remaining"));
        configuration.setMaxAge(3600L);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", configuration);
        return source;
    }

    private static void writeError(HttpServletResponse response, int status, String message) throws java.io.IOException {
        response.setStatus(status);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.getWriter().write("""
                {"status":%d,"message":"%s"}
                """.formatted(status, message));
    }
}
