package com.rag.gateway.user;

import java.util.Locale;

import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class UserService {
    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;

    public UserService(UserRepository userRepository, PasswordEncoder passwordEncoder) {
        this.userRepository = userRepository;
        this.passwordEncoder = passwordEncoder;
    }

    @Transactional
    public UserEntity register(RegisterRequest request) {
        String username = normalize(request.username());
        String email = normalizeEmail(request.email());

        if (userRepository.existsByUsername(username)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Username already exists");
        }
        if (userRepository.existsByEmail(email)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Email already exists");
        }

        UserEntity user = new UserEntity();
        user.setUsername(username);
        user.setEmail(email);
        user.setPasswordHash(passwordEncoder.encode(request.password()));
        return userRepository.save(user);
    }

    public UserEntity requireByUsername(String username) {
        return userRepository
                .findByUsername(username)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid credentials"));
    }

    public UserEntity authenticate(String username, String password) {
        UserEntity user = requireByUsername(normalize(username));
        if (!passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "Invalid credentials");
        }
        return user;
    }

    public void ensureDemoUser(String username, String password) {
        if (username == null || username.isBlank() || password == null || password.isBlank()) {
            return;
        }
        String normalizedUsername = normalize(username);
        if (userRepository.existsByUsername(normalizedUsername)) {
            return;
        }

        UserEntity user = new UserEntity();
        user.setUsername(normalizedUsername);
        user.setEmail(normalizedUsername + "@example.com");
        user.setPasswordHash(passwordEncoder.encode(password));
        userRepository.save(user);
    }

    private String normalize(String value) {
        return value == null ? "" : value.trim();
    }

    private String normalizeEmail(String value) {
        return value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    }
}
