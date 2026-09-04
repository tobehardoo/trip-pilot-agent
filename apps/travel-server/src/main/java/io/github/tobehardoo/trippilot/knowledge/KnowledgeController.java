package io.github.tobehardoo.trippilot.knowledge;

import java.util.List;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import io.github.tobehardoo.trippilot.knowledge.KnowledgeService.ImportInput;
import io.github.tobehardoo.trippilot.knowledge.KnowledgeService.ImportResult;
import io.github.tobehardoo.trippilot.knowledge.KnowledgeService.KnowledgeDetail;

/** 知识库管理接口（全局城市知识储备；需 JWT）。 */
@RestController
@RequestMapping("/api/knowledge")
public class KnowledgeController {

    private final KnowledgeService knowledgeService;

    public KnowledgeController(KnowledgeService knowledgeService) {
        this.knowledgeService = knowledgeService;
    }

    @GetMapping("/documents")
    KnowledgeService.KnowledgePage list(
            @RequestParam(required = false) String city,
            @RequestParam(required = false) String keyword,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size
    ) {
        return knowledgeService.list(city, keyword, page, size);
    }

    @GetMapping("/documents/{documentId}")
    KnowledgeService.KnowledgeDetail detail(@PathVariable String documentId) {
        return knowledgeService.detail(documentId);
    }

    @PutMapping("/documents/{documentId}")
    KnowledgeRecord edit(@PathVariable String documentId, @RequestBody KnowledgeService.EditInput input) {
        return knowledgeService.edit(documentId, input);
    }

    @DeleteMapping("/documents/{documentId}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    void delete(@PathVariable String documentId) {
        knowledgeService.delete(documentId);
    }

    @PostMapping("/documents/batch-delete")
    int deleteBatch(@RequestBody List<String> documentIds) {
        int before = documentIds.size();
        knowledgeService.deleteMany(documentIds);
        return before;
    }

    @GetMapping("/search")
    List<KnowledgeCitationRecord> search(
            @RequestParam String query,
            @RequestParam(required = false) String city,
            @RequestParam(required = false) String regionProvince,
            @RequestParam(required = false) String regionCity,
            @RequestParam(required = false) String regionDistrict,
            @RequestParam(required = false) String category,
            @RequestParam(required = false) String contentType,
            @RequestParam(required = false) String reliability,
            @RequestParam(defaultValue = "5") int limit,
            @RequestParam(defaultValue = "0.0") double minSimilarity,
            @RequestParam(defaultValue = "3") int topKPerDocument
    ) {
        return knowledgeService.search(query, city,
                regionProvince, regionCity, regionDistrict,
                category, contentType, reliability, limit, minSimilarity, topKPerDocument);
    }

    @PostMapping("/import")
    ImportResult importDocument(@RequestBody ImportInput input) {
        return knowledgeService.importDocument(input);
    }

    @ExceptionHandler(KnowledgeService.NotFound.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    String handleNotFound(KnowledgeService.NotFound exception) {
        return exception.getMessage();
    }

    @ExceptionHandler(IllegalArgumentException.class)
    @ResponseStatus(HttpStatus.BAD_REQUEST)
    String handleBadRequest(IllegalArgumentException exception) {
        return exception.getMessage();
    }
}