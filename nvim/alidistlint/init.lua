local M = {}

-- Configuration options
local config = {
  cmd = { "alidistlint" },
  filetypes = { "yaml" },
  root_dir = function(fname)
    return require("lspconfig.util").root_pattern("alidist")(fname) or
           require("lspconfig.util").root_pattern(".git")(fname) or
           vim.fn.getcwd()
  end,
  settings = {
    -- Add any settings here if needed
  },
}

function M.setup(opts)
  config = vim.tbl_deep_extend("force", config, opts or {})
  require("lspconfig").alidistlint.setup(config)
end

return M 