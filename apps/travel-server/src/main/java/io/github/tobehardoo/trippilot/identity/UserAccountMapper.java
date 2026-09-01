package io.github.tobehardoo.trippilot.identity;

import java.util.Optional;
import java.util.UUID;

import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

@Mapper
public interface UserAccountMapper {

    @Insert("""
            INSERT INTO business.user_account(id, email, password_hash, display_name)
            VALUES (#{id}, #{email}, #{passwordHash}, #{displayName})
            """)
    int insert(UserAccount user);

    @Select("""
            SELECT id, email, password_hash, display_name, created_at
            FROM business.user_account
            WHERE email = #{email}
            """)
    Optional<UserAccount> findByEmail(String email);

    @Select("""
            SELECT id, email, password_hash, display_name, created_at
            FROM business.user_account
            WHERE id = #{id}
            """)
    Optional<UserAccount> findById(UUID id);
}
