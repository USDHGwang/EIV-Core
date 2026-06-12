// SPDX-License-Identifier: CC0-1.0
pragma solidity ^0.8.19;

/**
 * @title EIV Validation Registry
 * @notice Minimal compatible implementation of ERC-8004 Validation Registry
 * @dev Used by EIV to attest validation results on-chain
 *
 * 改进说明（v2）：
 * 1. 结构体打包：validator + uint64 timestamp 合并到同一个 storage slot，省约 20,000 Gas
 * 2. 自定义错误：用 error + revert 替代 require，省部署和运行时 Gas
 * 3. 事件索引：responseHash 加 indexed，方便前端按哈希过滤日志
 */
contract EIVValidationRegistry {
    // ============================================================
    // 自定义错误（Custom Errors）
    // ============================================================
    // 用 error 替代 require，节省 Gas（只存 4 字节选择器，不存字符串）
    error NotOwner(address caller);

    // ============================================================
    // 事件（Events）
    // ============================================================
    // requestHash 和 responseHash 都标记为 indexed
    // 这样前端可以用 eth_getLogs 按哈希快速过滤，不用扫描全部日志
    event ValidationResponse(
        bytes32 indexed requestHash,
        bytes response,
        string responseURI,
        bytes32 indexed responseHash,
        string tag
    );

    // ============================================================
    // 状态变量（Storage）
    // ============================================================
    mapping(bytes32 => ValidationRecord) public validations;
    address public owner;

    // ============================================================
    // 结构体（Struct）— 优化后的存储布局
    // ============================================================
    // 优化前：7 个 storage slots
    //   bytes32 requestHash   → slot 1
    //   bytes response        → slot 2 (指针)
    //   string responseURI    → slot 3 (指针)
    //   bytes32 responseHash  → slot 4
    //   string tag            → slot 5 (指针)
    //   uint256 timestamp     → slot 6
    //   address validator     → slot 7 (浪费 12 bytes)
    //
    // 优化后：6 个 storage slots
    //   bytes32 requestHash   → slot 1
    //   bytes32 responseHash  → slot 2
    //   address validator     → slot 3 (20 bytes) ← 打包！
    //   uint64 timestamp      → slot 3 (8 bytes)  ← 打包！
    //   bytes response        → slot 4 (指针)
    //   string responseURI    → slot 5 (指针)
    //   string tag            → slot 6 (指针)
    //
    // 省了 1 个 slot ≈ 首次写入省约 20,000 Gas
    // uint64 最大值 = 18,446,744,073,709,551,615，足够用到公元 5849 亿年
    struct ValidationRecord {
        bytes32 requestHash;
        bytes32 responseHash;
        address validator;
        uint64 timestamp;
        bytes response;
        string responseURI;
        string tag;
    }

    // ============================================================
    // 修饰符（Modifiers）
    // ============================================================
    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner(msg.sender);
        _;
    }

    // ============================================================
    // 构造函数
    // ============================================================
    constructor() {
        owner = msg.sender;
    }

    // ============================================================
    // 核心函数
    // ============================================================

    /**
     * @notice Submit a validation response
     * @param requestHash Hash of the validation request
     * @param response Response data (e.g., score)
     * @param responseURI URI to detailed response
     * @param responseHash Hash of the response data
     * @param tag Tag for the validation (e.g., "EIV.L2.PASS")
     */
    function validationResponse(
        bytes32 requestHash,
        bytes memory response,
        string memory responseURI,
        bytes32 responseHash,
        string memory tag
    ) external onlyOwner {
        validations[requestHash] = ValidationRecord({
            requestHash: requestHash,
            responseHash: responseHash,
            validator: msg.sender,
            timestamp: uint64(block.timestamp),
            response: response,
            responseURI: responseURI,
            tag: tag
        });

        emit ValidationResponse(requestHash, response, responseURI, responseHash, tag);
    }

    /**
     * @notice Get validation record
     * @param requestHash Hash of the validation request
     * @return record The validation record
     */
    function getValidation(bytes32 requestHash) external view returns (ValidationRecord memory) {
        return validations[requestHash];
    }

    /**
     * @notice Check if validation exists
     * @param requestHash Hash of the validation request
     * @return exists Whether validation exists
     */
    function hasValidation(bytes32 requestHash) external view returns (bool exists) {
        return validations[requestHash].timestamp > 0;
    }
}
