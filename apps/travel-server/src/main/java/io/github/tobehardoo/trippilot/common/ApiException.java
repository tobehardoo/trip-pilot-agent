package io.github.tobehardoo.trippilot.common;

import org.springframework.http.HttpStatus;

public class ApiException extends RuntimeException {

    private final String code;
    private final HttpStatus status;

    public ApiException(HttpStatus status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    public String code() {
        return code;
    }

    public HttpStatus status() {
        return status;
    }
}
