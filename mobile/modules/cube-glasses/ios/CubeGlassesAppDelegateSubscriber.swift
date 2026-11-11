import ExpoModulesCore
import UIKit

/// Catches the callback URL (cubevision://…) the Meta AI app opens after registration or a
/// permission prompt, and hands it to the SDK — queueing it if JS hasn't initialised the SDK yet
/// (e.g. a cold launch straight from Meta AI).
public class CubeGlassesAppDelegateSubscriber: ExpoAppDelegateSubscriber {
  public func application(
    _ app: UIApplication,
    open url: URL,
    options: [UIApplication.OpenURLOptionsKey: Any] = [:]
  ) -> Bool {
    guard Self.isMetaCallback(url) else { return false }
    DispatchQueue.main.async {
      if let glasses = GlassesController.current {
        Task { await glasses.handle(url: url) }
      } else {
        GlassesController.pendingURLs.append(url)
      }
    }
    return true
  }

  private static func isMetaCallback(_ url: URL) -> Bool {
    guard let config = Bundle.main.object(forInfoDictionaryKey: "MWDAT") as? [String: Any],
          let scheme = config["AppLinkURLScheme"] as? String,
          let expected = URL(string: scheme)?.scheme
    else { return url.scheme == "cubevision" }
    return url.scheme == expected
  }
}
